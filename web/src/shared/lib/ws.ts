/**
 * useSessionWs — WebSocket 任务状态旁路。
 *
 * 连接到 /ws/chat/{sessionId}，接收 phase/task_log 等事件，
 * 转发给 applyEvent。SSE 是主通道；WS 供 TasksPanel 订阅者实时更新。
 */

import { useEffect, useRef } from "react";
import { useAuth } from "@/store/auth";
import { useChat } from "@/store/chat";

const BASE_WS = (() => {
  const api = (import.meta.env.VITE_API_BASE as string) || window.location.origin;
  return api.replace(/^http/, "ws");
})();

export function useSessionWs(sessionId: string | null) {
  const applyEvent = useChat((s) => s.applyEvent);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    const token = useAuth.getState().token;
    const url = `${BASE_WS}/ws/chat/${sessionId}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data as string);
        if (!ev || typeof ev.type !== "string") return;
        // approval_required 只经 WS 推送，始终 apply。
        if (ev.type === "approval_required") {
          applyEvent(ev);
          return;
        }
        // phase/task_log 同时经 SSE 主通道送达：本端正在驱动该轮（turn.inFlight）时
        // 交给 SSE 处理、WS 跳过——否则 task_log 会被 append 两次而每行重复。
        // inFlight=false 时本端是纯旁观者（无 SSE 流），靠 WS 实时更新面板。
        if (ev.type === "phase" || ev.type === "task_log") {
          if (!useChat.getState().turn.inFlight) applyEvent(ev);
        }
        // 其余事件 WS 不处理（SSE 主通道负责）。
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      // silent — SSE is primary; WS is best-effort
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [sessionId, applyEvent]);
}
