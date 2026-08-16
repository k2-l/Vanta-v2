import { useState, useRef, useEffect } from "react";
import { useChat } from "@/store/chat";
import { useSend } from "../useSend";
import { api, type BudgetStatus } from "@/shared/lib/api";
import { EnvSelector } from "./EnvSelector";
import { CompressModal } from "./CompressModal";

function fmt(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(n);
}

export function ChatInput() {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const inFlight = useChat((s) => s.turn.inFlight);
  const currentId = useChat((s) => s.currentSessionId);
  const endTurn = useChat((s) => s.endTurn);
  const setAbortStream = useChat((s) => s.setAbortStream);
  const usage = useChat((s) => s.turn.usage);
  const sendMsg = useSend();
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [showCompress, setShowCompress] = useState(false);

  // 每次 turn 结束后拉取一次 budget 数据
  useEffect(() => {
    if (!currentId || inFlight) return;
    api.budget(currentId).then(setBudget).catch(() => {});
  }, [currentId, inFlight]);

  useEffect(() => {
    if (!inFlight) ref.current?.focus();
  }, [inFlight]);

  // textarea 随内容自动长高（封顶 140px 后内部滚动）
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [value]);

  function send() {
    const text = value.trim();
    if (!text) return;
    setValue("");
    sendMsg(text);
  }

  function stop() {
    useChat.getState().abortStream?.();
    setAbortStream(null);
    endTurn();
  }

  const contextUsed = (usage?.sessionIn ?? 0) + (usage?.sessionOut ?? 0);
  const contextMax = 200000;
  const ctxPct = contextMax > 0 ? Math.min(100, Math.round((contextUsed / contextMax) * 100)) : 0;
  const turnIn = usage?.turnIn ?? 0;
  const turnOut = usage?.turnOut ?? 0;
  const turnCache = 0;
  const turnTotal = turnIn + turnOut;

  return (
    <div style={{ flexShrink: 0, background: "#FFFFFF", borderTop: "1px solid #E2E5EA" }}>
      {/* 输入行：textarea 可多行、随内容长高；发送按钮贴底 */}
      <div style={{ display: "flex", gap: 10, padding: "12px 20px", alignItems: "flex-end" }}>
        <textarea
          ref={ref}
          rows={1}
          style={{
            flex: 1,
            background: "#F9FAFB",
            border: "1px solid #E2E5EA",
            borderRadius: 10,
            padding: "9px 16px",
            color: "#1A1D23",
            fontSize: 13,
            lineHeight: 1.5,
            outline: "none",
            fontFamily: "inherit",
            resize: "none",
            minHeight: 40,
            maxHeight: 140,
            overflowY: "auto",
            boxSizing: "border-box",
          }}
          placeholder={inFlight ? "处理中…" : "向 Master Agent 发送指令…（Shift+Enter 换行）"}
          value={value}
          disabled={inFlight}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") { setValue(""); return; }
            // Enter 发送；Shift+Enter 换行；中文输入法组字期间的 Enter 不发送
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        {inFlight ? (
          <button
            onClick={stop}
            style={{
              width: 40,
              height: 40,
              flexShrink: 0,
              borderRadius: 10,
              background: "#EF444418",
              border: "1px solid #EF444444",
              color: "#EF4444",
              fontSize: 14,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "inherit",
            }}
          >
            ■
          </button>
        ) : (
          <button
            onClick={send}
            disabled={!value.trim()}
            style={{
              width: 40,
              height: 40,
              flexShrink: 0,
              borderRadius: 10,
              background: "linear-gradient(135deg,#4F6EF722,#7C3AED22)",
              border: "1px solid #4F6EF744",
              color: "#4F6EF7",
              fontSize: 18,
              cursor: value.trim() ? "pointer" : "default",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              opacity: value.trim() ? 1 : 0.4,
            }}
          >
            ↑
          </button>
        )}
      </div>

      {/* HUD 状态条 */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 24,
        padding: "7px 20px",
        borderTop: "1px solid #E2E5EA",
        minHeight: 36,
        boxSizing: "border-box",
      }}>
        <span style={{ fontSize: 11, color: "#9BA3AF", letterSpacing: 1 }}>
          # {currentId ? currentId.slice(0, 16) : "—"}
        </span>
        <span style={{ fontSize: 10, color: "#C0C5CE", whiteSpace: "nowrap" }}>
          ↵ 发送 · ⇧↵ 换行 · Esc 清空
        </span>
        <EnvSelector />
        <div style={{ display: "flex", gap: 20, flex: 1, justifyContent: "center" }}>
          {[
            { label: "输入", val: turnIn,    c: "#4F6EF7" },
            { label: "输出", val: turnOut,   c: "#10B981" },
            { label: "缓存", val: turnCache, c: "#F59E0B" },
            { label: "总量", val: turnTotal, c: "#1A1D23" },
          ].map((t) => (
            <div key={t.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: t.c }}>{fmt(t.val)}</span>
              <span style={{ fontSize: 9, color: "#9BA3AF", letterSpacing: 1 }}>{t.label}</span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* 上下文窗口 */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 9, color: "#9BA3AF", letterSpacing: 1 }}>上下文</span>
            <div style={{ width: 60, height: 4, background: "#E2E5EA", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ height: "100%", background: "linear-gradient(90deg,#4F6EF7,#7C3AED)", borderRadius: 2, width: ctxPct + "%" }} />
            </div>
            <span style={{ fontSize: 10, color: "#6B7280" }}>{fmt(contextUsed)}</span>
          </div>
          {/* 主动压缩：上下文偏高时高亮为「建议压缩」 */}
          <button
            onClick={() => setShowCompress(true)}
            disabled={!currentId || inFlight}
            title="把当前对话压成摘要作背景，原文保留可回退"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              padding: "4px 10px",
              borderRadius: 8,
              fontSize: 11,
              fontFamily: "inherit",
              cursor: currentId && !inFlight ? "pointer" : "default",
              opacity: currentId && !inFlight ? 1 : 0.4,
              border: ctxPct >= 80 ? "1px solid #F59E0B66" : "1px solid #E2E5EA",
              background: ctxPct >= 80 ? "#F59E0B14" : "#FFFFFF",
              color: ctxPct >= 80 ? "#B45309" : "#6B7280",
            }}
          >
            ⇲ {ctxPct >= 80 ? "建议压缩" : "压缩"}
          </button>
          {/* 会话配额 */}
          {budget && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 9, color: "#9BA3AF", letterSpacing: 1 }}>配额</span>
              <div style={{ width: 50, height: 4, background: "#E2E5EA", borderRadius: 2, overflow: "hidden" }} title={`会话 ${budget.session.percent}% · 今日 ${budget.daily.percent}%`}>
                <div style={{
                  height: "100%",
                  background: budget.session.percent > 80 ? "#EF4444" : "#10B981",
                  borderRadius: 2,
                  width: Math.min(100, budget.session.percent) + "%",
                }} />
              </div>
              <span style={{ fontSize: 10, color: budget.session.percent > 80 ? "#EF4444" : "#6B7280" }}>
                {budget.session.percent}%
              </span>
            </div>
          )}
        </div>
      </div>

      {showCompress && currentId && (
        <CompressModal sessionId={currentId} onClose={() => setShowCompress(false)} />
      )}
    </div>
  );
}
