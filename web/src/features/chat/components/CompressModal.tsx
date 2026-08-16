import { useEffect, useState } from "react";
import { api, type CompressPreview } from "@/shared/lib/api";

function fmt(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(n);
}

/**
 * 主动压缩上下文弹窗：预览 → 可编辑 → 确认生效。
 * 采用「压缩检查点」：原文一条不删（可回退），确认后从检查点起只把摘要+新消息喂给模型。
 */
export function CompressModal({
  sessionId,
  onClose,
  onDone,
}: {
  sessionId: string;
  onClose: () => void;
  onDone?: () => void;
}) {
  const [preview, setPreview] = useState<CompressPreview | null>(null);
  const [summary, setSummary] = useState("");
  const [phase, setPhase] = useState<"loading" | "ready" | "committing">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setPhase("loading");
    setError(null);
    api
      .compressPreview(sessionId)
      .then((p) => {
        if (!alive) return;
        setPreview(p);
        setSummary(p.summary);
        setPhase("ready");
      })
      .catch((e) => {
        if (!alive) return;
        setError(String(e?.message || e));
        setPhase("ready");
      });
    return () => {
      alive = false;
    };
  }, [sessionId]);

  async function confirm() {
    if (!preview || !summary.trim()) return;
    setPhase("committing");
    setError(null);
    try {
      await api.compressCommit(sessionId, summary, preview.upto);
      onDone?.();
      onClose();
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
      setPhase("ready");
    }
  }

  const saved = preview ? preview.tokens_before - preview.tokens_after : 0;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "#0B0D1288",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(680px, 92vw)",
          maxHeight: "86vh",
          background: "#FFFFFF",
          border: "1px solid #E2E5EA",
          borderRadius: 14,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 24px 60px #0B0D1233",
        }}
      >
        {/* 标题 */}
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #E2E5EA" }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#1A1D23" }}>压缩上下文</div>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 4, lineHeight: 1.5 }}>
            把当前对话提炼成一份结构化摘要作背景，之后在此基础上继续。
            <b style={{ color: "#4F6EF7" }}> 原文一条不删，可随时回退。</b>
          </div>
        </div>

        {/* 主体 */}
        <div style={{ padding: 20, overflowY: "auto", flex: 1 }}>
          {phase === "loading" ? (
            <div style={{ padding: "40px 0", textAlign: "center", color: "#9BA3AF", fontSize: 13 }}>
              正在生成摘要…
            </div>
          ) : (
            <>
              {preview && (
                <div
                  style={{
                    display: "flex",
                    gap: 20,
                    marginBottom: 14,
                    padding: "10px 14px",
                    background: "#F9FAFB",
                    borderRadius: 10,
                    border: "1px solid #E2E5EA",
                    fontSize: 12,
                  }}
                >
                  <Stat label="压缩条数" value={String(preview.messages)} c="#1A1D23" />
                  <Stat label="压缩前" value={fmt(preview.tokens_before) + " tok"} c="#6B7280" />
                  <Stat label="压缩后" value={fmt(preview.tokens_after) + " tok"} c="#10B981" />
                  <Stat label="预计节省" value={fmt(Math.max(0, saved)) + " tok"} c="#4F6EF7" />
                </div>
              )}

              <div style={{ fontSize: 11, color: "#9BA3AF", letterSpacing: 1, marginBottom: 6 }}>
                摘要（可编辑）
              </div>
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                disabled={phase === "committing"}
                style={{
                  width: "100%",
                  minHeight: 260,
                  background: "#F9FAFB",
                  border: "1px solid #E2E5EA",
                  borderRadius: 10,
                  padding: "12px 14px",
                  color: "#1A1D23",
                  fontSize: 13,
                  lineHeight: 1.6,
                  outline: "none",
                  resize: "vertical",
                  fontFamily: "inherit",
                  boxSizing: "border-box",
                }}
              />

              {error && (
                <div style={{ marginTop: 10, color: "#EF4444", fontSize: 12, lineHeight: 1.5 }}>
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {/* 底部按钮 */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            padding: "12px 20px",
            borderTop: "1px solid #E2E5EA",
          }}
        >
          <button onClick={onClose} disabled={phase === "committing"} style={btn(false)}>
            取消
          </button>
          <button
            onClick={confirm}
            disabled={phase !== "ready" || !summary.trim()}
            style={btn(true, phase === "ready" && !!summary.trim())}
          >
            {phase === "committing" ? "应用中…" : "确认压缩"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, c }: { label: string; value: string; c: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: c }}>{value}</span>
      <span style={{ fontSize: 9, color: "#9BA3AF", letterSpacing: 1 }}>{label}</span>
    </div>
  );
}

function btn(primary: boolean, enabled = true): React.CSSProperties {
  return {
    padding: "8px 18px",
    borderRadius: 9,
    fontSize: 13,
    cursor: enabled ? "pointer" : "default",
    fontFamily: "inherit",
    border: primary ? "1px solid #4F6EF744" : "1px solid #E2E5EA",
    background: primary ? "linear-gradient(135deg,#4F6EF7,#7C3AED)" : "#FFFFFF",
    color: primary ? "#FFFFFF" : "#6B7280",
    opacity: enabled ? 1 : 0.45,
  };
}
