/**
 * useSend — 封装 LLM 消息发送逻辑。
 *
 * 返回 `send(text)` 函数，ChatInput 和重试按钮共用同一逻辑：
 *   1. 检查 inFlight（已在处理中则跳过）
 *   2. 调用 beginTurn
 *   3. 启动 chatStream
 *   4. onClose：正常结束
 *   5. onError（非用户主动终止）：等 2s 轮询消息列表
 *      - 若 assistant 已回复 → setMessages 更新 UI，不重发
 *      - 若无回复 → workerFailed = true，显示重试按钮
 */
import { useChat } from "@/store/chat";
import { chatStream } from "@/shared/lib/sse";
import { api } from "@/shared/lib/api";

const RECONNECT_DELAY_MS = 2000;

export function useSend(): (text: string) => void {
  const currentId = useChat((s) => s.currentSessionId);
  const executionEnv = useChat((s) => s.executionEnv);
  const beginTurn = useChat((s) => s.beginTurn);
  const applyEvent = useChat((s) => s.applyEvent);
  const endTurn = useChat((s) => s.endTurn);
  const setAbortStream = useChat((s) => s.setAbortStream);
  const setMessages = useChat((s) => s.setMessages);

  return (text: string) => {
    // Read inFlight from store directly — closure would capture a stale value
    // from the last render, allowing double-submit before React re-renders.
    if (!text.trim() || useChat.getState().turn.inFlight) return;
    beginTurn(text);

    async function onError() {
      setAbortStream(null);
      // 等待 backend 可能还在处理中
      await new Promise((r) => setTimeout(r, RECONNECT_DELAY_MS));
      try {
        if (!currentId) { endTurn(); return; }
        const msgs = await api.getMessages(currentId);
        const lastAsst = [...msgs].reverse().find((m) => m.role === "assistant");
        const lastUser = [...msgs].reverse().find((m) => m.role === "user");
        // 如果 assistant 回复比用户消息更新，说明处理完成了
        if (lastAsst && lastUser && lastAsst.created_at >= lastUser.created_at) {
          setMessages(msgs);
          endTurn();          // 正常结束
          return;
        }
      } catch { /* ignore */ }
      endTurn();              // 标记 workerFailed，显示重试按钮
    }

    const abort = chatStream(text, currentId, executionEnv, {
      onEvent: applyEvent,
      onError: () => { void onError(); },
      onClose: () => { setAbortStream(null); endTurn(); },
    });
    setAbortStream(abort);
  };
}
