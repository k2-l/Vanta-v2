/**
 * 统一事件信封与前端运行投影（方案 §10.2 / §10.4）。
 *
 * 事件在进入前端前由 Rust EventBridge 做 schema 校验、去重、附加序号，
 * 前端只维护「投影」（projection），不直接消费原始传输流。
 */

export const EVENT_SCHEMA_VERSION = 1 as const;

/** 目标事件类型（方案 §10.3）。unknown event 由客户端忽略并记录，不得使流崩溃。 */
export type EventType =
  | "run.created"
  | "run.started"
  | "run.completed"
  | "run.failed"
  | "run.cancelled"
  | "invocation.started"
  | "invocation.status"
  | "invocation.completed"
  | "message.delta"
  | "message.completed"
  | "tool.started"
  | "tool.completed"
  | "tool.failed"
  | "critic.completed"
  | "critic.retry_requested"
  | "approval.required"
  | "approval.resolved"
  | "approval.expired"
  | "artifact.created"
  | "artifact.updated"
  | "usage.recorded"
  | "budget.warning"
  | "budget.exhausted"
  | "heartbeat"
  | "stream.reset";

/** 统一事件信封。第一阶段兼容层由 Rust 从现有 SSE/WS 合成此形状。 */
export type EventEnvelope<P = unknown> = {
  schemaVersion: number;
  eventId: string;
  /** 同一 run 内单调递增。 */
  seq: number;
  timestamp: string;
  runId: string;
  sessionId: string;
  invocationId?: string;
  parentInvocationId?: string;
  type: EventType | (string & {});
  payload: P;
};

export type RunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "unknown";

export type InvocationStatus =
  | "started"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "unknown";

/** 单个 Agent 调用投影——父子 token 预算彼此独立（方案 §3）。 */
export type InvocationProjection = {
  invocationId: string;
  parentInvocationId?: string;
  agentName?: string;
  status: InvocationStatus;
  depth: number;
  /** 直接子委派 id（用于「≤3 同时直接委派」的表达）。 */
  childInvocationIds: string[];
  /** 独立 invocation token 用量，绝不与父子共用一个递减池。 */
  usage?: TokenUsage;
  criticScore?: number;
  toolCallIds: string[];
};

export type TokenUsage = {
  inputTokens: number;
  outputTokens: number;
  /** 该 invocation 的独立预算上限（若已知）。 */
  budgetLimit?: number;
};

/** 运行投影（方案 §10.4）——与聊天消息分开存储。 */
export type RunProjection = {
  runId: string;
  sessionId: string;
  status: RunStatus;
  rootInvocationId: string;
  invocations: Record<string, InvocationProjection>;
  pendingApprovals: string[];
  artifactIds: string[];
  /** 已应用的最大 seq，用于 after_seq 重放与去重。 */
  lastSeq: number;
};

export function emptyRunProjection(runId: string, sessionId: string, rootInvocationId: string): RunProjection {
  return {
    runId,
    sessionId,
    status: "queued",
    rootInvocationId,
    invocations: {},
    pendingApprovals: [],
    artifactIds: [],
    lastSeq: 0,
  };
}
