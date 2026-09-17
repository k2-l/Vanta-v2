/**
 * 会话主动压缩控件——对话输入框下方的按钮 + 预览/编辑/提交弹窗。
 *
 * 流程（对齐后端两步式）：点击「压缩上下文」→ 生成结构化摘要预览（不落库）→
 * 用户可编辑摘要 → 「应用压缩」写入检查点。原文始终保留、可回退，
 * transcript 不变；压缩改变的是后续运行装载的历史与 token 预算。
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Check, FoldVertical, Loader2, X } from "lucide-react";
import { Button } from "@/components/Button";
import { toClientError } from "@/contracts/errors";
import { formatTokens } from "@/lib/format";
import { useCompactionCommit, useCompactionPreview } from "./useCompaction";

export function CompactionControl({ sessionId, disabled }: { sessionId: string; disabled?: boolean }) {
  const preview = useCompactionPreview();
  const commit = useCompactionCommit();
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const [committed, setCommitted] = useState(false);

  const start = () => {
    setCommitted(false);
    setSummary("");
    commit.reset();
    preview.reset();
    setOpen(true);
    preview.mutate({ sessionId }, { onSuccess: (data) => setSummary(data.summary) });
  };

  const close = () => {
    if (commit.isPending) return; // 提交进行中不关闭，避免写一半状态不明
    setOpen(false);
  };

  const apply = () => {
    const data = preview.data;
    const text = summary.trim();
    if (!data || !text) return;
    commit.mutate(
      { sessionId, summary: text, upto: data.upto },
      { onSuccess: () => setCommitted(true) },
    );
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, commit.isPending]);

  return (
    <>
      <div className="mx-auto mt-2 flex max-w-3xl items-center justify-center">
        <button
          type="button"
          disabled={disabled}
          onClick={start}
          title="把较早的历史压成结构化摘要，节省上下文 token（原文保留、可回退）"
          className="inline-flex items-center gap-1.5 rounded-[var(--radius)] px-2 py-1 text-[11px] transition-colors hover:bg-[var(--surface-inset)] disabled:opacity-40 disabled:pointer-events-none"
          style={{ color: "var(--fg-muted)" }}
        >
          <FoldVertical size={13} />
          压缩上下文
        </button>
      </div>

      {open &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label="会话主动压缩"
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(0,0,0,0.45)" }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) close();
            }}
          >
            <div
              className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-xl"
              style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
            >
              <header
                className="flex items-center justify-between border-b px-4 py-3"
                style={{ borderColor: "var(--border)" }}
              >
                <div className="flex items-center gap-2">
                  <FoldVertical size={15} style={{ color: "var(--accent)" }} />
                  <h2 className="text-[13px] font-semibold" style={{ color: "var(--fg)" }}>
                    压缩会话上下文
                  </h2>
                </div>
                <button
                  aria-label="关闭"
                  onClick={close}
                  disabled={commit.isPending}
                  className="rounded-[var(--radius-sm)] p-1 transition-colors hover:bg-[var(--surface-inset)] disabled:opacity-40"
                  style={{ color: "var(--fg-muted)" }}
                >
                  <X size={15} />
                </button>
              </header>

              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {preview.isPending ? (
                  <div className="flex items-center gap-2 py-10 text-[12px]" style={{ color: "var(--fg-muted)" }}>
                    <Loader2 size={15} className="animate-spin" />
                    正在生成压缩摘要…
                  </div>
                ) : preview.isError ? (
                  <div
                    className="rounded-[var(--radius)] border px-3 py-3 text-[12px]"
                    style={{ borderColor: "var(--danger)", background: "var(--danger-tint)", color: "var(--fg)" }}
                  >
                    <p className="mb-2">生成压缩摘要失败：{toClientError(preview.error).message}</p>
                    <Button size="xs" variant="secondary" onClick={start}>
                      重试
                    </Button>
                  </div>
                ) : preview.data ? (
                  <>
                    <p className="mb-3 text-[12px] leading-relaxed" style={{ color: "var(--fg-muted)" }}>
                      已把较早的 <b style={{ color: "var(--fg)" }}>{preview.data.messages}</b> 条历史压成结构化摘要。
                      提交后，后续对话将以此摘要作为更早历史的背景；<b style={{ color: "var(--fg)" }}>原文保留、可回退</b>，当前消息记录不受影响。
                    </p>

                    <div className="mb-3 flex flex-wrap gap-2">
                      <Stat label="压缩消息" value={`${preview.data.messages} 条`} />
                      <Stat label="压缩前" value={`${formatTokens(preview.data.tokens_before)} tok`} />
                      <Stat label="压缩后" value={`${formatTokens(preview.data.tokens_after)} tok`} />
                      <Stat label="节省" value={reductionLabel(preview.data.tokens_before, preview.data.tokens_after)} accent />
                    </div>

                    <label className="mb-1 block text-[11px] font-medium" style={{ color: "var(--fg-muted)" }}>
                      摘要（可编辑）
                    </label>
                    <textarea
                      value={summary}
                      onChange={(event) => setSummary(event.target.value)}
                      disabled={commit.isPending || committed}
                      rows={12}
                      className="select-text w-full resize-y rounded-[var(--radius)] border bg-transparent p-3 font-mono text-[12px] leading-relaxed outline-none focus:border-[var(--accent-line)] disabled:opacity-60"
                      style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                    />

                    {committed && (
                      <div className="mt-3 flex items-center gap-2 text-[12px]" style={{ color: "var(--ok, var(--accent))" }}>
                        <Check size={14} />
                        已应用压缩，后续对话将使用该摘要作为背景。
                      </div>
                    )}
                    {commit.isError && (
                      <p className="mt-3 text-[12px]" style={{ color: "var(--danger)" }}>
                        提交失败：{toClientError(commit.error).message}
                      </p>
                    )}
                  </>
                ) : null}
              </div>

              <footer
                className="flex items-center justify-end gap-2 border-t px-4 py-3"
                style={{ borderColor: "var(--border)" }}
              >
                {committed ? (
                  <Button size="sm" onClick={close}>
                    完成
                  </Button>
                ) : (
                  <>
                    <Button size="sm" variant="secondary" onClick={close} disabled={commit.isPending}>
                      取消
                    </Button>
                    <Button
                      size="sm"
                      onClick={apply}
                      disabled={!preview.data || !summary.trim() || commit.isPending}
                    >
                      {commit.isPending ? <Loader2 size={14} className="animate-spin" /> : <FoldVertical size={14} />}
                      应用压缩
                    </Button>
                  </>
                )}
              </footer>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      className="rounded-[var(--radius)] border px-2.5 py-1.5"
      style={{
        borderColor: accent ? "var(--accent-line)" : "var(--border)",
        background: accent ? "var(--accent-tint)" : "var(--surface-inset)",
      }}
    >
      <div className="text-[10px]" style={{ color: "var(--fg-subtle)" }}>
        {label}
      </div>
      <div className="text-[13px] font-medium" style={{ color: accent ? "var(--accent)" : "var(--fg)" }}>
        {value}
      </div>
    </div>
  );
}

function reductionLabel(before: number, after: number): string {
  if (!Number.isFinite(before) || before <= 0) return "—";
  const pct = Math.round((1 - after / before) * 100);
  return pct > 0 ? `↓ ${pct}%` : `${pct}%`;
}
