/**
 * 流式事件契约（Plan §5.1 Chat stream）——与后端 `harness/core/foundation/events.py`
 * 的 SSE 事件类型逐一对齐。Rust `stream.rs` 把每个 SSE 帧转成 `{event, data}`，
 * 并额外合成 `stream.closed` / `client_error`；`run_subscribe` 轮询快照时合成 `snapshot`。
 *
 * 字段兼容用显式别名，不在 UI 层猜测多种格式（Plan §5）。
 */

import type { ClientError } from "./errors";

/** 后端阶段状态（PhaseEvent.status）。 */
export type PhaseWireStatus = "pending" | "running" | "ok" | "failed";

/** 单个后端事件负载（data 字段）。 */
export type TextDeltaData = { type: "text_delta"; role: "worker"; text: string; task_id?: string };
export type ToolCallData = {
  type: "tool_call";
  role: "worker";
  tool: string;
  inputs: Record<string, unknown>;
  task_id?: string;
};
export type ToolResultData = {
  type: "tool_result";
  role: "worker";
  tool: string;
  ok: boolean;
  output: string;
  error?: string | null;
  task_id?: string;
};
export type ToolErrorData = {
  type: "tool_error";
  role: "worker";
  tool: string;
  error_code: string;
  message: string;
  retryable: boolean;
  task_id?: string;
};
export type WorkerStartData = { type: "worker_start"; worker: string; instruction: string; task_id?: string };
export type WorkerEndData = {
  type: "worker_end";
  worker: string;
  status: "ok" | "failed";
  summary: string;
  task_id?: string;
};
export type UsageData = {
  type: "usage";
  model: string;
  turn_input: number;
  turn_output: number;
  turn_cost_usd: number;
  session_input: number;
  session_output: number;
  session_cost_usd: number;
};
export type PhaseData = {
  type: "phase";
  id: string;
  label?: string;
  status?: PhaseWireStatus;
  detail?: string;
  task_id?: string;
  parent_id?: string;
};
export type TaskLogData = { type: "task_log"; task_id?: string; message?: string };

/** GET /sessions/{id}/phases 的一行（run 快照）；run_subscribe 亦以此形状回传。 */
export type PhaseSnapshotRow = {
  id: string;
  session_id?: string;
  parent_id?: string | null;
  type?: string;
  status?: PhaseWireStatus;
  label?: string;
  payload?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
};

/** GET /runs 的列表行；状态由服务端基于 phases 一次聚合。 */
export type RunSummaryWire = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  steps: number;
};

export type StreamClosedReason = "completed" | "cancelled" | "failed" | "receiver_closed";

/**
 * 归一化后的流包（event 判别联合，全字面量以支持窄化）。
 * 运行时若到达未列出的 event，仍会经 Channel 送达，由 reducer 的 default 分支忽略，
 * 不使流崩溃（events.ts §10.3）。
 */
export type StreamPacket =
  | { event: "session"; data: string }
  | { event: "text_delta"; data: TextDeltaData }
  | { event: "tool_call"; data: ToolCallData }
  | { event: "tool_result"; data: ToolResultData }
  | { event: "tool_error"; data: ToolErrorData }
  | { event: "worker_start"; data: WorkerStartData }
  | { event: "worker_end"; data: WorkerEndData }
  | { event: "usage"; data: UsageData }
  | { event: "phase"; data: PhaseData }
  | { event: "task_log"; data: TaskLogData }
  | { event: "done"; data: { type: "done" } }
  | { event: "snapshot"; data: { phases: PhaseSnapshotRow[]; seq: number } }
  | { event: "stream.closed"; data: { reason: StreamClosedReason } }
  | { event: "client_error"; data: ClientError };
