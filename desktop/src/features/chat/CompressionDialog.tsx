import * as Dialog from "@radix-ui/react-dialog";
import { Check, FileText, X } from "lucide-react";
import { Button } from "@/components/Button";
import type { CompressPreview } from "@/contracts/chat";

export function CompressionDialog({
  preview,
  summary,
  pending,
  onSummaryChange,
  onCommit,
  onClose,
}: {
  preview: CompressPreview | null;
  summary: string;
  pending: boolean;
  onSummaryChange: (value: string) => void;
  onCommit: () => void;
  onClose: () => void;
}) {
  const saved = preview ? Math.max(0, preview.tokens_before - preview.tokens_after) : 0;
  const ratio = preview?.tokens_before
    ? Math.max(0, Math.round((saved / preview.tokens_before) * 100))
    : 0;

  return (
    <Dialog.Root open={Boolean(preview)} onOpenChange={(open) => !open && !pending && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[78vh] w-[min(680px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-lg)] border p-5 shadow-2xl outline-none"
          style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
          aria-describedby="compression-description"
        >
          <div className="flex items-start gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius)]" style={{ background: "var(--accent-tint)", color: "var(--accent)" }}>
              <FileText size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[15px] font-semibold" style={{ color: "var(--fg)" }}>
                确认上下文压缩
              </Dialog.Title>
              <Dialog.Description id="compression-description" className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--fg-muted)" }}>
                摘要会替代检查点之前的消息进入后续模型上下文；原始消息仍完整保留，可在对话历史中查看。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild disabled={pending}>
              <button className="grid h-7 w-7 place-items-center rounded-md hover:bg-[var(--surface-inset)] disabled:opacity-40" aria-label="关闭">
                <X size={15} />
              </button>
            </Dialog.Close>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2">
            <Metric label="纳入消息" value={`${preview?.messages ?? 0} 条`} />
            <Metric label="估算 Token" value={`${preview?.tokens_before ?? 0} → ${preview?.tokens_after ?? 0}`} />
            <Metric label="预计减少" value={`${ratio}%`} />
          </div>

          <label className="mt-4 flex min-h-0 flex-1 flex-col gap-2">
            <span className="text-[12px] font-medium" style={{ color: "var(--fg)" }}>结构化摘要（可编辑）</span>
            <textarea
              value={summary}
              onChange={(event) => onSummaryChange(event.target.value)}
              disabled={pending}
              className="min-h-56 flex-1 resize-y select-text rounded-[var(--radius)] border px-3 py-2.5 text-[13px] leading-relaxed outline-none focus:border-[var(--accent-line)] disabled:opacity-60"
              style={{ background: "var(--surface-inset)", borderColor: "var(--border)", color: "var(--fg)" }}
              aria-label="压缩摘要"
            />
          </label>

          <div className="mt-4 flex items-center justify-end gap-2">
            <Button size="sm" variant="ghost" disabled={pending} onClick={onClose}>取消</Button>
            <Button size="sm" disabled={pending || !summary.trim()} onClick={onCommit}>
              <Check size={14} />
              {pending ? "正在应用…" : "应用压缩"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius)] border px-3 py-2" style={{ background: "var(--surface-inset)", borderColor: "var(--border)" }}>
      <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>{label}</p>
      <p className="mt-1 text-[12px] font-medium" style={{ color: "var(--fg)" }}>{value}</p>
    </div>
  );
}
