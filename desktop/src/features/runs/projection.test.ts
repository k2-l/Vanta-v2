import { describe, expect, it } from "vitest";
import type { RunEventWire, StreamPacket } from "@/contracts/stream";
import { applyPacket, applyPhasesSnapshot, deriveTimeline, emptyProjection } from "./projection";
import { projectionFromHistory } from "./useRuns";

describe("run projection", () => {
  it("folds public text, tools, usage and completion into one view model", () => {
    const packets: StreamPacket[] = [
      { event: "session", data: "session-1" },
      { event: "text_delta", data: { type: "text_delta", role: "worker", text: "公开回答", task_id: "agent" } },
      { event: "text_delta", data: { type: "text_delta", role: "worker", text: "内部输出", task_id: "child" } },
      { event: "tool_call", data: { type: "tool_call", role: "worker", tool: "shell", inputs: { cmd: "pwd" }, task_id: "agent" } },
      { event: "tool_result", data: { type: "tool_result", role: "worker", tool: "shell", ok: true, output: "/tmp", task_id: "agent" } },
      {
        event: "usage",
        data: {
          type: "usage",
          model: "test-model",
          turn_input: 120,
          turn_output: 30,
          turn_cost_usd: 0.01,
          session_input: 500,
          session_output: 100,
          session_cost_usd: 0.03,
        },
      },
      { event: "done", data: { type: "done" } },
    ];

    const result = packets.reduce(applyPacket, emptyProjection());
    expect(result.sessionId).toBe("session-1");
    expect(result.assistant).toBe("公开回答");
    expect(result.tools).toHaveLength(1);
    expect(result.tools[0]).toMatchObject({ tool: "shell", status: "ok", output: "/tmp" });
    expect(result.usage?.sessionInput).toBe(500);
    expect(result.status).toBe("completed");
  });

  it("rebuilds an out-of-order phase tree and preserves a failed terminal state", () => {
    const result = applyPhasesSnapshot(emptyProjection("session-2"), [
      { id: "child", parent_id: "root", label: "子任务", status: "failed" },
      { id: "root", label: "主任务", status: "ok" },
    ], 4);

    expect(result.phases.root.children).toEqual(["child"]);
    expect(result.status).toBe("failed");
    expect(deriveTimeline(result).map((item) => item.label)).toEqual(["子任务", "主任务"]);
  });

  it("ignores an already applied snapshot sequence", () => {
    const current = applyPhasesSnapshot(
      emptyProjection("session-3"),
      [{ id: "root", label: "原状态", status: "running" }],
      5,
    );
    const duplicate = applyPhasesSnapshot(
      current,
      [{ id: "root", label: "过期状态", status: "ok" }],
      5,
    );

    expect(duplicate).toBe(current);
    expect(duplicate.phases.root.label).toBe("原状态");
  });

  it("restores historical tools and token usage alongside the phase snapshot", () => {
    const events: RunEventWire[] = [
      {
        seq: 1,
        event: "tool_call",
        data: { type: "tool_call", role: "worker", tool: "shell", inputs: { cmd: "pwd" }, task_id: "agent" },
        created_at: "2026-09-15T00:00:00Z",
      },
      {
        seq: 2,
        event: "tool_result",
        data: { type: "tool_result", role: "worker", tool: "shell", ok: true, output: "/workspace", task_id: "agent" },
        created_at: "2026-09-15T00:00:01Z",
      },
      {
        seq: 3,
        event: "usage",
        data: { type: "usage", model: "test-model", turn_input: 80, turn_output: 20, turn_cost_usd: 0, session_input: 800, session_output: 200, session_cost_usd: 0 },
        created_at: "2026-09-15T00:00:02Z",
      },
    ];
    const result = projectionFromHistory(
      "session-history",
      [{
        id: "agent",
        label: "已完成",
        status: "ok",
        created_at: "2026-09-15T00:00:00Z",
        updated_at: "2026-09-15T00:00:03Z",
      }],
      events,
    );

    expect(result.status).toBe("completed");
    expect(result.tools[0]).toMatchObject({ tool: "shell", status: "ok", output: "/workspace" });
    expect(result.usage?.sessionInput).toBe(800);
    expect(result.durationMs).toBe(3000);
  });
});
