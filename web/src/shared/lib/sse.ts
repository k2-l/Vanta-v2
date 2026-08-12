/**
 * SSE 聊天流客户端：基于 @microsoft/fetch-event-source。
 * 比浏览器原生 EventSource 强：可发 POST、可加 headers、可中断。
 *
 * 自动注入 Authorization 头；遇 401 调 forceLogout。
 */

import { fetchEventSource } from "@microsoft/fetch-event-source";
import { authHeader, useAuth } from "@/store/auth";

const BASE = (import.meta.env.VITE_API_BASE as string) || window.location.origin;

// 后端事件类型对照（agent/events.py）
export type HarnessEvent =
  | { type: "session"; session_id: string }
  | { type: "text_delta"; role: "supervisor" | "worker" | "critic"; text: string; task_id?: string }
  | { type: "tool_call"; tool: string; inputs: Record<string, unknown>; task_id?: string }
  | { type: "tool_result"; tool: string; ok: boolean; output: string; error?: string | null; task_id?: string }
  | { type: "worker_start"; worker: string; instruction: string; task_id?: string }
  | { type: "worker_end"; worker: string; status: "ok" | "failed"; summary: string; task_id?: string }
  | { type: "usage"; model: string; turn_input: number; turn_output: number; turn_cost_usd: number; session_input: number; session_output: number; session_cost_usd: number }
  | { type: "phase"; id: string; label: string; status: "pending" | "running" | "ok" | "failed"; detail?: string; task_id?: string; parent_id?: string }
  | { type: "task_log"; task_id?: string; message: string }
  | { type: "tool_error"; tool: string; error_code: string; message: string; retryable: boolean; task_id?: string }
  | { type: "approval_required"; call_id: string; tool_name: string; message: string } // HITL 审批门（仅 WS 推送，见 harness/infra/approvals.py）
  | { type: "done" };

export interface ChatStreamHandlers {
  onEvent: (ev: HarnessEvent) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
}

/**
 * 打开 /chat SSE 流。返回 abort 函数。
 */
export function chatStream(
  message: string,
  sessionId: string | null,
  executionEnv: string,
  handlers: ChatStreamHandlers
): () => void {
  const ctrl = new AbortController();

  // Guard against onClose being called more than once.
  // Normal path: done event → close() + ctrl.abort() (skips onclose callback).
  // Fallback path: unexpected server close → onclose callback → close() (no-op if already closed).
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    handlers.onClose?.();
  }

  fetchEventSource(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ message, session_id: sessionId, execution_env: executionEnv }),
    signal: ctrl.signal,
    openWhenHidden: true, // 切到后台时不要断
    async onopen(resp) {
      if (resp.status === 401) {
        useAuth.getState().forceLogout("登录已失效，请重新登录");
        throw new Error("401 Unauthorized");
      }
      if (!resp.ok) {
        throw new Error(`SSE 连接失败：${resp.status} ${resp.statusText}`);
      }
    },
    onmessage(ev) {
      // 后端用 sse-starlette，event/data 行
      const eventName = ev.event || "";
      const data = ev.data ?? "";
      if (eventName === "session") {
        handlers.onEvent({ type: "session", session_id: data });
        return;
      }
      if (eventName === "done") {
        handlers.onEvent({ type: "done" });
        // Abort before the library can call onclose — ctrl.abort() causes
        // fetchEventSource to check signal.aborted and return without retry,
        // without calling onerror, and without calling onclose.
        close();
        ctrl.abort();
        return;
      }
      if (!data) return;
      try {
        const payload = JSON.parse(data) as HarnessEvent;
        handlers.onEvent(payload);
      } catch {
        // 解析失败忽略
      }
    },
    onerror(err) {
      handlers.onError?.(err);
      // 默认会自动重连，这里抛出阻断重连
      throw err;
    },
    onclose() {
      // Only reached for unexpected server close (no 'done' received).
      // Normal close already handled via ctrl.abort() in onmessage above.
      close();
    },
  }).catch(() => {
    /* 已通过 onerror/onclose 处理 */
  });

  return () => ctrl.abort();
}
