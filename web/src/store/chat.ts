/**
 * 聊天与会话的全局状态（zustand）。
 */

import { create } from "zustand";
import type { Message } from "@/shared/lib/api";
import type { HarnessEvent } from "@/shared/lib/sse";


// ─── 流事件渲染模型（单任务模式专用）────────────────────────────────────
export type StreamItem =
  | { kind: "worker_step"; worker: string; instruction: string; stepNo: number }
  | { kind: "tool_call"; tool: string; inputs: Record<string, unknown>; result?: { ok: boolean; output: string } }
  | { kind: "tool_error"; tool: string; error_code: string; message: string; retryable: boolean }
  | { kind: "text"; content: string };

// 完成轮的 assistant 消息可携带分步渲染项（streamItems）：让"结束态"和"实时态"一样按步骤分块，
// 而非塌成一个大文本块。后端历史消息（刷新后 getMessages）无此字段 → 回退纯文本渲染。
export type ChatMessage = Message & { items?: StreamItem[] };

export type Phase = {
  id: string;
  label: string;
  status: "pending" | "running" | "ok" | "failed" | "pass" | "revise";
  detail?: string;
  parent_id?: string;
};

// HITL 工具审批门（item 6）：后端通过 WS 推送 approval_required 事件填充
export type PendingApproval = {
  call_id: string;
  tool_name: string;
  message: string;
};

export type TurnState = {
  inFlight: boolean;
  userText: string;                    // 启动该轮的用户消息（用作 TasksPanel 分组标题）
  workerFailed: boolean;               // 上一轮 worker_end 状态为 failed
  inPlanMode: boolean;
  streamItems: StreamItem[];            // 当前轮流事件序列（渲染用）
  stepCounter: number;                   // 单任务步骤计数
  responseBuffer: string;                // 文本累积（供 endTurn 提交）
  finalResponse: string;                 // synthesis_end 综合输出
  taskLogs: Record<string, string[]>;
  taskLabels: Record<string, string>;
  phases: Phase[];
  planSummary: string;
  usage: {
    turnIn: number; turnOut: number; turnCost: number;
    sessionIn: number; sessionOut: number; sessionCost: number;
  } | null;
};

const emptyTurn: TurnState = {
  inFlight: false,
  userText: "",
  workerFailed: false,
  inPlanMode: false,
  streamItems: [],
  stepCounter: 0,
  responseBuffer: "",
  finalResponse: "",
  taskLogs: {},
  taskLabels: {},
  phases: [],
  planSummary: "",
  usage: null,
};

// ─── localStorage 持久化（phases / taskLogs / usage，不含 streamItems）───
const CACHE_KEY = "harness.turnCache";
const CACHE_MAX = 30;

type PersistedTurn = Pick<TurnState, "phases" | "taskLogs" | "taskLabels" | "usage">;

// TasksPanel 按轮分组累积展示（每会话内存保留，不写 localStorage）：每轮一组任务数据。
// 解决「新一轮覆盖上一轮 agent 日志」——上一轮结束的数据在 beginTurn 时归档为一组。
export type TurnGroup = {
  id: string;
  userText: string;
  ts: string;
  phases: Phase[];
  taskLogs: Record<string, string[]>;
  taskLabels: Record<string, string>;
};
const TASK_GROUPS_MAX = 20;   // 每会话最多保留的历史轮次组数（防长会话无限增长）

function loadCache(): Record<string, TurnState> {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, PersistedTurn>;
    return Object.fromEntries(
      Object.entries(parsed).map(([id, t]) => [id, { ...emptyTurn, ...t }])
    );
  } catch { return {}; }
}

function saveCache(cache: Record<string, TurnState>) {
  try {
    const entries = Object.entries(cache).slice(-CACHE_MAX);
    const slim = Object.fromEntries(
      entries.map(([id, t]) => [id, {
        phases:     t.phases,
        taskLogs:   t.taskLogs,
        taskLabels: t.taskLabels,
        usage:      t.usage,
      } satisfies PersistedTurn])
    );
    localStorage.setItem(CACHE_KEY, JSON.stringify(slim));
  } catch { /* storage quota 满时静默忽略 */ }
}

// ─── TasksPanel 轮次分组持久化（跨刷新保留历史轮）─────────────────────────
const TASK_GROUPS_KEY = "harness.taskGroups";
const TASK_GROUPS_SESSIONS_MAX = 20;   // 持久化的会话数上限（防 localStorage 膨胀）

function loadTaskGroups(): Record<string, TurnGroup[]> {
  try {
    const raw = localStorage.getItem(TASK_GROUPS_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, TurnGroup[]>;
  } catch { return {}; }
}

function saveTaskGroups(groups: Record<string, TurnGroup[]>) {
  try {
    const entries = Object.entries(groups).slice(-TASK_GROUPS_SESSIONS_MAX);
    // 持久化时给每个任务的日志行数封顶（最近 80 行），避免长 agent 运行撑爆
    // localStorage 触发 quota；实时态（store 内存）仍保留完整日志。
    const slim: Record<string, TurnGroup[]> = {};
    for (const [sid, list] of entries) {
      slim[sid] = list.map((g) => ({
        ...g,
        taskLogs: Object.fromEntries(
          Object.entries(g.taskLogs).map(([k, v]) => [k, v.slice(-80)]),
        ),
      }));
    }
    localStorage.setItem(TASK_GROUPS_KEY, JSON.stringify(slim));
  } catch { /* storage quota 满时静默忽略 */ }
}

// ─── 执行环境持久化（刷新后保留所选容器，而非回退物理机）────────────────
const EXEC_ENV_KEY = "harness.executionEnv";
function loadExecutionEnv(): string {
  try { return localStorage.getItem(EXEC_ENV_KEY) || "local"; } catch { return "local"; }
}

type State = {
  currentSessionId: string | null;
  messages: ChatMessage[];
  turn: TurnState;
  executionEnv: string;
  pendingApprovals: PendingApproval[];

  setCurrentSession: (id: string | null) => void;
  setMessages: (m: Message[]) => void;
  appendMessage: (m: Message) => void;
  setExecutionEnv: (env: string) => void;
  dismissApproval: (callId: string) => void;

  beginTurn: (userText: string) => void;
  applyEvent: (ev: HarnessEvent) => void;
  endTurn: () => void;

  // SSE 流中止（切换会话时自动调用）
  abortStream: (() => void) | null;
  setAbortStream: (fn: (() => void) | null) => void;

  // 会话 turn 状态缓存（切换会话时保留 phases）
  turnCache: Record<string, TurnState>;

  // 每会话的历史轮次任务分组（供 TasksPanel 累积展示，内存态）
  taskGroups: Record<string, TurnGroup[]>;
};

export const useChat = create<State>((set, get) => ({
  currentSessionId: null,
  messages: [],
  turn: emptyTurn,
  executionEnv: loadExecutionEnv(),
  pendingApprovals: [],

  turnCache: loadCache(),
  taskGroups: loadTaskGroups(),

  setExecutionEnv: (executionEnv) => {
    try { localStorage.setItem(EXEC_ENV_KEY, executionEnv); } catch { /* ignore */ }
    set({ executionEnv });
  },
  dismissApproval: (callId) =>
    set((s) => ({ pendingApprovals: s.pendingApprovals.filter((p) => p.call_id !== callId) })),
  setCurrentSession: (currentSessionId) => {
    const { currentSessionId: oldId, turn: oldTurn } = get();

    // 中止正在流式的请求
    get().abortStream?.();

    if (oldId === currentSessionId) return;

    // 缓存旧会话的 turn 状态（仅在有内容时缓存）
    const cache = { ...get().turnCache };
    if (oldId && (oldTurn.phases.length > 0 || oldTurn.streamItems.length > 0)) {
      cache[oldId] = { ...oldTurn, inFlight: false };
    }

    // 恢复目标会话的缓存 turn，或空状态
    const restored = currentSessionId && cache[currentSessionId]
      ? { ...cache[currentSessionId] }
      : { ...emptyTurn };

    set({ currentSessionId, turn: restored, turnCache: cache, abortStream: null });
  },
  setMessages: (messages) => set({ messages }),
  appendMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  abortStream: null,
  setAbortStream: (fn) => set({ abortStream: fn }),

  beginTurn: (userText) => {
    const id = crypto.randomUUID();
    set((s) => {
      const turnCache = { ...s.turnCache };
      if (s.currentSessionId) delete turnCache[s.currentSessionId];
      saveCache(turnCache);
      // 归档上一轮（已结束、有任务数据）为一个轮次分组，避免被本轮覆盖
      const taskGroups = { ...s.taskGroups };
      if (s.currentSessionId && s.turn.phases.length > 0) {
        const prev: TurnGroup = {
          id: crypto.randomUUID(),
          userText: s.turn.userText,
          ts: new Date().toISOString(),
          phases: s.turn.phases,
          taskLogs: s.turn.taskLogs,
          taskLabels: s.turn.taskLabels,
        };
        taskGroups[s.currentSessionId] = [
          ...(taskGroups[s.currentSessionId] || []),
          prev,
        ].slice(-TASK_GROUPS_MAX);
        saveTaskGroups(taskGroups);
      }
      return {
        turn: { ...emptyTurn, inFlight: true, userText },
        messages: [
          ...s.messages,
          { id, role: "user", content: userText, created_at: new Date().toISOString() },
        ],
        turnCache,
        taskGroups,
      };
    });
  },

  endTurn: () => {
    const { turn, messages, currentSessionId, turnCache } = get();
    const finalText = turn.finalResponse || turn.responseBuffer;
    const next = [...messages];
    if (finalText.trim() || turn.streamItems.length > 0) {
      next.push({
        id: crypto.randomUUID(),
        role: "assistant",
        content: finalText,
        created_at: new Date().toISOString(),
        // 保留分步结构（工具卡/步骤/文本段），供 MessageList 分块渲染，不再塌成一片
        items: turn.streamItems.length > 0 ? turn.streamItems : undefined,
      });
    }
    // 安全兜底：turn 结束时将所有仍在 "running" 的 phase 标为 "ok"
    // 防止后端漏发 PhaseEvent(status="ok") 导致状态卡住
    const settledPhases = turn.phases.map((p) =>
      p.status === "running" ? { ...p, status: "ok" as const } : p
    );
    const finishedTurn = { ...turn, inFlight: false, phases: settledPhases };
    // 缓存已完成 turn 的状态
    const cache = { ...turnCache };
    if (currentSessionId && finishedTurn.phases.length > 0) {
      cache[currentSessionId] = finishedTurn;
    }
    saveCache(cache);
    set({ messages: next, turn: finishedTurn, turnCache: cache, pendingApprovals: [] });
  },

  applyEvent: (ev) => {
    set((s) => {
      const t: TurnState = {
        ...s.turn,
        streamItems: [...s.turn.streamItems],
        taskLogs: { ...s.turn.taskLogs },
        taskLabels: { ...s.turn.taskLabels },
        phases: [...s.turn.phases],
      };

      switch (ev.type) {

        case "session":
          return { ...s, currentSessionId: ev.session_id };

        // HITL 审批门（item 6）：仅 WS 推送，与 turn 状态无关
        case "approval_required":
          return {
            ...s,
            pendingApprovals: [
              ...s.pendingApprovals.filter((p) => p.call_id !== ev.call_id),
              { call_id: ev.call_id, tool_name: ev.tool_name, message: ev.message },
            ],
          };

        // ── 共用 ──────────────────────────────────────────────────────
        case "worker_start": {
          const tid = ev.task_id || "single";
          if (!t.inPlanMode) {
            const stepNo = t.stepCounter + 1;
            t.stepCounter = stepNo;
            t.streamItems = [
              ...t.streamItems,
              { kind: "worker_step", worker: ev.worker, instruction: ev.instruction, stepNo },
            ];
            // 稳定排序：已存在则原地更新，不存在才追加（避免 phase 跳到末尾、实时跑时发跳）
            const _wi = t.phases.findIndex((p) => p.id === tid);
            const _wlabel = `${ev.worker}: ${ev.instruction.slice(0, 50)}`;
            if (_wi >= 0) {
              t.phases[_wi] = { ...t.phases[_wi], label: _wlabel, status: "running" };
            } else {
              t.phases = [...t.phases, { id: tid, label: _wlabel, status: "running" }];
            }
          } else {
            t.phases = t.phases.map((p) =>
              p.id === tid ? { ...p, status: "running" as const } : p
            );
            t.taskLabels[tid] = ev.instruction.slice(0, 60);
            t.taskLogs[tid] = [
              ...(t.taskLogs[tid] || []),
              `── 启动：${ev.instruction.slice(0, 60)} ──`,
            ];
          }
          break;
        }

        case "worker_end": {
          const tid = ev.task_id || "single";
          t.workerFailed = ev.status !== "ok";
          t.phases = t.phases.map((p) =>
            p.id === tid
              ? { ...p, status: ev.status === "ok" ? ("ok" as const) : ("failed" as const), detail: ev.summary?.slice(0, 80) }
              : p
          );
          if (t.inPlanMode) {
            t.taskLogs[tid] = [
              ...(t.taskLogs[tid] || []),
              `── 结束 status=${ev.status} ──`,
              ...(ev.summary ? [ev.summary] : []),
            ];
          }
          break;
        }

        case "text_delta": {
          if (ev.role !== "worker") break;
          if (t.inPlanMode) {
            const tid = ev.task_id || "single";
            t.taskLogs[tid] = [...(t.taskLogs[tid] || []), ev.text];
          } else {
            const last = t.streamItems[t.streamItems.length - 1];
            if (last && last.kind === "text") {
              t.streamItems = [
                ...t.streamItems.slice(0, -1),
                { kind: "text", content: last.content + ev.text },
              ];
            } else {
              t.streamItems = [...t.streamItems, { kind: "text", content: ev.text }];
            }
            t.responseBuffer += ev.text;
          }
          break;
        }

        case "tool_call": {
          const tid = ev.task_id || "single";
          if (t.inPlanMode) {
            t.taskLogs[tid] = [
              ...(t.taskLogs[tid] || []),
              `→ ${ev.tool}(${JSON.stringify(ev.inputs).slice(0, 100)})`,
            ];
          } else {
            t.streamItems = [
              ...t.streamItems,
              { kind: "tool_call", tool: ev.tool, inputs: ev.inputs },
            ];
          }
          break;
        }

        case "tool_result": {
          const tid = ev.task_id || "single";
          if (t.inPlanMode) {
            t.taskLogs[tid] = [
              ...(t.taskLogs[tid] || []),
              `← ${ev.ok ? "" : "(error) "}${(ev.output || "").slice(0, 200)}`,
            ];
          } else {
            // 找最后一个没有 result 的 tool_call，附上结果
            const items = [...t.streamItems];
            for (let i = items.length - 1; i >= 0; i--) {
              const item = items[i];
              if (item.kind === "tool_call" && !item.result) {
                items[i] = { ...item, result: { ok: ev.ok, output: ev.output } };
                break;
              }
            }
            t.streamItems = items;
          }
          break;
        }

        case "tool_error": {
          const tid = ev.task_id || "single";
          if (t.inPlanMode) {
            t.taskLogs[tid] = [
              ...(t.taskLogs[tid] || []),
              `✗ [${ev.error_code}] ${ev.tool}: ${ev.message}`,
            ];
          } else {
            t.streamItems = [
              ...t.streamItems,
              { kind: "tool_error", tool: ev.tool, error_code: ev.error_code, message: ev.message, retryable: ev.retryable },
            ];
          }
          break;
        }

        case "usage": {
          t.usage = {
            turnIn: ev.turn_input,
            turnOut: ev.turn_output,
            turnCost: ev.turn_cost_usd,
            sessionIn: ev.session_input,
            sessionOut: ev.session_output,
            sessionCost: ev.session_cost_usd,
          };
          break;
        }

        case "phase": {
          const pid = ev.task_id || ev.id;
          console.debug("phase event", pid, ev.label, ev.status, ev.parent_id);
          const idx = t.phases.findIndex((p) => p.id === pid);
          if (idx >= 0) {
            t.phases[idx] = { ...t.phases[idx], status: ev.status, detail: ev.detail ?? t.phases[idx].detail, label: ev.label || t.phases[idx].label };
          } else {
            const newPhase: Phase = { id: pid, label: ev.label, status: ev.status, detail: ev.detail };
            if (ev.parent_id) newPhase.parent_id = ev.parent_id;
            t.phases = [...t.phases, newPhase];
          }
          break;
        }

        case "task_log": {
          const tlid = ev.task_id || "single";
          t.taskLogs[tlid] = [...(t.taskLogs[tlid] || []), ev.message];
          break;
        }

        case "done":
          break;
      }

      return { ...s, turn: t };
    });
  },
}));
