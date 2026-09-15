/**
 * 运行投影（事件归一化，Plan G2）——把后端流事件折叠成稳定的前端 view model。
 *
 * 纯函数、不可变返回，便于 React 状态更新与单测。一个「run」= 一个 session 的执行；
 * 「invocation/Agent 树」= phase 树（id/parent_id）。对话页在流式期间实时构建投影，
 * 运行页用 phases 快照（REST）重建同一形状（Plan：run≈session）。
 */

import type { Tone } from "@/components/desktop/status";
import type {
  PhaseSnapshotRow,
  PhaseWireStatus,
  StreamPacket,
} from "@/contracts/stream";

const ROOT_TASK_IDS = new Set(["", "agent"]);

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type PhaseStatus = PhaseWireStatus;
export type ToolStatus = "running" | "ok" | "failed";

export const RUN_STATUS_META: Record<RunStatus, { label: string; tone: Tone }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "运行中", tone: "running" },
  completed: { label: "已完成", tone: "ok" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
};

export const PHASE_TONE: Record<PhaseStatus, Tone> = {
  pending: "neutral",
  running: "running",
  ok: "ok",
  failed: "danger",
};

export type PhaseNode = {
  id: string;
  parentId?: string;
  label: string;
  status: PhaseStatus;
  detail?: string;
  taskId?: string;
  order: number;
  children: string[];
};

export type ToolEvent = {
  key: string;
  taskId: string;
  tool: string;
  inputs?: Record<string, unknown>;
  status: ToolStatus;
  output?: string;
  error?: string;
  errorCode?: string;
  retryable?: boolean;
  order: number;
};

export type RunUsage = {
  model?: string;
  turnInput: number;
  turnOutput: number;
  turnCostUsd: number;
  sessionInput: number;
  sessionOutput: number;
  sessionCostUsd: number;
};

export type RunProjection = {
  sessionId?: string;
  status: RunStatus;
  /** 可见回答（root worker 的公开 text_delta 累积）。 */
  assistant: string;
  phases: Record<string, PhaseNode>;
  phaseOrder: string[];
  tools: ToolEvent[];
  usage?: RunUsage;
  logs: { taskId: string; message: string; order: number }[];
  lastError?: { message: string; retryable: boolean };
  /** 已应用事件计数，用作稳定排序时间戳。 */
  order: number;
  /** run_subscribe 快照去重游标。 */
  snapshotSeq: number;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
};

export function emptyProjection(sessionId?: string): RunProjection {
  return {
    sessionId,
    status: "queued",
    assistant: "",
    phases: {},
    phaseOrder: [],
    tools: [],
    logs: [],
    order: 0,
    snapshotSeq: 0,
  };
}

function upsertPhase(
  p: RunProjection,
  id: string,
  patch: Partial<Omit<PhaseNode, "id" | "order" | "children">>,
  order: number,
): void {
  const existing = p.phases[id];
  if (existing) {
    p.phases[id] = { ...existing, ...stripUndefined(patch) };
    return;
  }
  const node: PhaseNode = {
    id,
    label: patch.label ?? id,
    status: patch.status ?? "running",
    parentId: patch.parentId,
    detail: patch.detail,
    taskId: patch.taskId,
    order,
    children: [],
  };
  p.phases[id] = node;
  p.phaseOrder.push(id);
  if (node.parentId && p.phases[node.parentId]) {
    p.phases[node.parentId] = {
      ...p.phases[node.parentId],
      children: [...p.phases[node.parentId].children, id],
    };
  }
}

function stripUndefined<T extends object>(obj: T): Partial<T> {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(obj)) if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  return out;
}

/**
 * 应用一个流包，返回新的投影（不可变）。未知 event 原样忽略，不使流崩溃。
 */
export function applyPacket(prev: RunProjection, packet: StreamPacket): RunProjection {
  const p: RunProjection = {
    ...prev,
    phases: { ...prev.phases },
    phaseOrder: [...prev.phaseOrder],
    tools: [...prev.tools],
    logs: [...prev.logs],
    order: prev.order + 1,
  };
  const order = p.order;

  switch (packet.event) {
    case "session":
      if (typeof packet.data === "string") p.sessionId = packet.data;
      if (p.status === "queued") p.status = "running";
      return p;

    case "text_delta": {
      if (p.status === "queued") p.status = "running";
      const taskId = packet.data.task_id ?? "";
      if (ROOT_TASK_IDS.has(taskId)) p.assistant += packet.data.text;
      return p;
    }

    case "phase": {
      if (p.status === "queued") p.status = "running";
      const parentId = packet.data.parent_id && !ROOT_TASK_IDS.has(packet.data.parent_id)
        ? packet.data.parent_id
        : packet.data.parent_id === "agent"
          ? "agent"
          : undefined;
      upsertPhase(
        p,
        packet.data.id,
        {
          label: packet.data.label || undefined,
          status: packet.data.status,
          detail: packet.data.detail || undefined,
          taskId: packet.data.task_id || undefined,
          parentId,
        },
        order,
      );
      return p;
    }

    case "tool_call": {
      if (p.status === "queued") p.status = "running";
      p.tools.push({
        key: `${packet.data.task_id ?? ""}:${packet.data.tool}:${order}`,
        taskId: packet.data.task_id ?? "",
        tool: packet.data.tool,
        inputs: packet.data.inputs,
        status: "running",
        order,
      });
      return p;
    }

    case "tool_result": {
      resolveTool(p, packet.data.tool, packet.data.task_id ?? "", (t) => ({
        ...t,
        status: packet.data.ok ? "ok" : "failed",
        output: packet.data.output,
        error: packet.data.error ?? undefined,
      }));
      return p;
    }

    case "tool_error": {
      resolveTool(p, packet.data.tool, packet.data.task_id ?? "", (t) => ({
        ...t,
        status: "failed",
        errorCode: packet.data.error_code,
        error: packet.data.message,
        retryable: packet.data.retryable,
      }));
      return p;
    }

    case "worker_end": {
      // 根 worker 失败 → 整个 run 失败（子 worker 失败仍可被上层恢复）。
      if (packet.data.status === "failed" && ROOT_TASK_IDS.has(packet.data.task_id ?? "")) {
        p.status = "failed";
      }
      return p;
    }

    case "usage":
      p.usage = {
        model: packet.data.model || undefined,
        turnInput: packet.data.turn_input,
        turnOutput: packet.data.turn_output,
        turnCostUsd: packet.data.turn_cost_usd,
        sessionInput: packet.data.session_input,
        sessionOutput: packet.data.session_output,
        sessionCostUsd: packet.data.session_cost_usd,
      };
      return p;

    case "task_log":
      if (packet.data.message) {
        p.logs.push({ taskId: packet.data.task_id ?? "", message: packet.data.message, order });
      }
      return p;

    case "done":
      if (p.status !== "failed" && p.status !== "cancelled") p.status = "completed";
      return p;

    case "snapshot":
      return applyPhasesSnapshot(p, packet.data.phases, packet.data.seq);

    case "stream.closed":
      if (packet.data.reason === "cancelled") p.status = "cancelled";
      else if (packet.data.reason === "failed") p.status = "failed";
      else if (packet.data.reason === "completed" && p.status === "running") p.status = "completed";
      return p;

    case "client_error": {
      const err = packet.data as { message?: string; retryable?: boolean };
      p.lastError = { message: err.message ?? "流错误", retryable: Boolean(err.retryable) };
      if (p.status === "running" || p.status === "queued") p.status = "failed";
      return p;
    }

    default:
      // worker_start 及未知事件：不改变树（phases 已是权威结构）。
      return p;
  }
}

function resolveTool(
  p: RunProjection,
  tool: string,
  taskId: string,
  update: (t: ToolEvent) => ToolEvent,
): void {
  for (let i = p.tools.length - 1; i >= 0; i -= 1) {
    const t = p.tools[i];
    if (t.tool === tool && t.taskId === taskId && t.status === "running") {
      p.tools[i] = update(t);
      return;
    }
  }
}

/**
 * 用 phases 快照（REST GET /sessions/{id}/phases，或 run_subscribe snapshot 包）重建/对账。
 * 幂等：按 phase id upsert；用于运行页详情与断线重连（重新拉快照而非按 seq 重放）。
 */
export function applyPhasesSnapshot(
  prev: RunProjection,
  rows: PhaseSnapshotRow[],
  seq?: number,
): RunProjection {
  if (seq !== undefined && seq <= prev.snapshotSeq) return prev;
  const p: RunProjection = {
    ...prev,
    phases: { ...prev.phases },
    phaseOrder: [...prev.phaseOrder],
    order: prev.order,
    snapshotSeq: seq ?? prev.snapshotSeq,
  };
  rows.forEach((row, index) => {
    const parentId = row.parent_id && !ROOT_TASK_IDS.has(row.parent_id) ? row.parent_id : undefined;
    const payloadDetail = (row.payload as { detail?: string } | null | undefined)?.detail;
    upsertPhase(
      p,
      row.id,
      {
        label: row.label || (row.payload as { label?: string } | null)?.label || undefined,
        status: row.status,
        detail: payloadDetail || undefined,
        parentId,
      },
      prev.order + index + 1,
    );
  });
  // 快照行顺序不保证父节点先于子节点；统一重建 children，避免子节点被误判为根节点。
  for (const id of p.phaseOrder) {
    p.phases[id] = { ...p.phases[id], children: [] };
  }
  for (const id of p.phaseOrder) {
    const node = p.phases[id];
    if (node.parentId && p.phases[node.parentId]) {
      p.phases[node.parentId] = {
        ...p.phases[node.parentId],
        children: [...p.phases[node.parentId].children, id],
      };
    }
  }
  p.order = prev.order + rows.length + 1;
  if (rows.length > 0 && p.status !== "cancelled") p.status = deriveRunStatus(p);
  const starts = rows
    .map((row) => row.created_at)
    .filter((value): value is string => Boolean(value))
    .map((value) => ({ value, time: new Date(value).getTime() }))
    .filter((item) => Number.isFinite(item.time));
  const updates = rows
    .map((row) => row.updated_at)
    .filter((value): value is string => Boolean(value))
    .map((value) => ({ value, time: new Date(value).getTime() }))
    .filter((item) => Number.isFinite(item.time));
  if (starts.length > 0) {
    const started = starts.reduce((earliest, item) => (item.time < earliest.time ? item : earliest));
    p.startedAt = started.value;
    const terminal = p.status === "completed" || p.status === "failed" || p.status === "cancelled";
    const finished = terminal && updates.length > 0
      ? updates.reduce((latest, item) => (item.time > latest.time ? item : latest))
      : undefined;
    p.finishedAt = finished?.value;
    p.durationMs = Math.max(0, (finished?.time ?? Date.now()) - started.time);
  }
  return p;
}

/** 从 phase 状态汇总出整体 run 状态（历史 run 无流事件时用）。 */
export function deriveRunStatus(p: RunProjection): RunStatus {
  const phases = Object.values(p.phases);
  if (phases.length === 0) return p.status;
  if (phases.some((ph) => ph.status === "running" || ph.status === "pending")) return "running";
  if (phases.some((ph) => ph.status === "failed")) return "failed";
  return "completed";
}

/** 根阶段（无父，或父不在集合内）。 */
export function rootPhases(p: RunProjection): PhaseNode[] {
  return p.phaseOrder
    .map((id) => p.phases[id])
    .filter((ph) => !ph.parentId || !p.phases[ph.parentId]);
}

export type RunTimelineTone = Tone;

/** 时间线：phases + 工具事件按发生顺序合并。 */
export function deriveTimeline(p: RunProjection): {
  id: string;
  label: string;
  detail?: string;
  tone: RunTimelineTone;
  order: number;
}[] {
  const phaseItems = p.phaseOrder.map((id) => {
    const ph = p.phases[id];
    return { id: `p_${id}`, label: ph.label, detail: ph.detail, tone: PHASE_TONE[ph.status], order: ph.order };
  });
  const toolItems = p.tools.map((t) => ({
    id: `t_${t.key}`,
    label: `工具 ${t.tool}`,
    detail: t.status === "failed" ? (t.error ?? "失败") : t.status === "ok" ? "完成" : "调用中",
    tone: t.status === "failed" ? ("danger" as Tone) : t.status === "ok" ? ("ok" as Tone) : ("running" as Tone),
    order: t.order,
  }));
  return [...phaseItems, ...toolItems].sort((a, b) => a.order - b.order);
}

export function phaseCount(p: RunProjection): number {
  return p.phaseOrder.length;
}

export function toolCount(p: RunProjection): number {
  return p.tools.length;
}
