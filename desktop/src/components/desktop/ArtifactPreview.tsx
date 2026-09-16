/**
 * 产物预览（规范 §4.4）——文档 / 图片 / 文本内置预览；未知或高风险类型只显示元数据。
 * 导出必须经 Rust Core 的安全路径选择与能力检查，因此导出按钮受 exportSupported 约束。
 * 纯展示组件，只接收归一化 model。
 */

import { useEffect, useState } from "react";
import { Activity, Download, FileWarning, ImageIcon, MessageSquare, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/Button";
import { DetailField } from "./DetailPanel";

export type PreviewKind = "markdown" | "text" | "code" | "image" | "none";

export type ArtifactPreviewModel = {
  id: string;
  name: string;
  typeLabel: string;
  sizeLabel: string;
  sourceSession: string;
  updatedAtLabel: string;
  previewKind: PreviewKind;
  preview?: string;
  highRisk?: boolean;
  /** 后端是否声明了 artifactExport 能力。 */
  exportSupported: boolean;
  exportDisabledReason?: string;
};

export function ArtifactPreview({
  model,
  onExport,
  onDelete,
  onOpenSourceChat,
  onOpenSourceRun,
  exporting = false,
  deleting = false,
}: {
  model: ArtifactPreviewModel;
  onExport?: () => void;
  onDelete?: () => void;
  onOpenSourceChat?: () => void;
  onOpenSourceRun?: () => void;
  exporting?: boolean;
  deleting?: boolean;
}) {
  // 两步内联确认：首点转「确认删除？」，再点才真删；切换产物或失焦即复位。
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  useEffect(() => setConfirmingDelete(false), [model.id]);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header
        className="flex shrink-0 items-start justify-between gap-3 border-b px-5 py-3"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-semibold" style={{ color: "var(--fg)" }}>
            {model.name}
          </h2>
          <p className="mt-0.5 text-[11px]" style={{ color: "var(--fg-muted)" }}>
            {model.typeLabel} · {model.sizeLabel} · {model.sourceSession} · {model.updatedAtLabel}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {onOpenSourceChat && (
            <Button size="sm" variant="ghost" onClick={onOpenSourceChat} title="打开来源会话">
              <MessageSquare size={14} />
              会话
            </Button>
          )}
          {onOpenSourceRun && (
            <Button size="sm" variant="ghost" onClick={onOpenSourceRun} title="打开来源运行">
              <Activity size={14} />
              运行
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            disabled={!model.exportSupported || exporting}
            title={model.exportSupported ? "由本机 Rust Core 导出到系统下载目录" : (model.exportDisabledReason ?? "服务器未声明导出能力")}
            onClick={onExport}
          >
            <Download size={14} />
            {exporting ? "导出中…" : "导出"}
          </Button>
          {onDelete && (
            <Button
              size="sm"
              variant={confirmingDelete ? "danger" : "dangerGhost"}
              disabled={deleting}
              title="删除该产物（不可撤销）"
              onClick={() => {
                if (confirmingDelete) {
                  onDelete();
                  setConfirmingDelete(false);
                } else {
                  setConfirmingDelete(true);
                }
              }}
              onBlur={() => setConfirmingDelete(false)}
            >
              <Trash2 size={14} />
              {deleting ? "删除中…" : confirmingDelete ? "确认删除？" : "删除"}
            </Button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-5">
        <PreviewBody model={model} />
      </div>
    </div>
  );
}

function PreviewBody({ model }: { model: ArtifactPreviewModel }) {
  if (model.highRisk || model.previewKind === "none") {
    return (
      <div className="mx-auto max-w-md">
        <div
          className="flex flex-col items-center gap-3 rounded-[var(--radius-lg)] border p-8 text-center"
          style={{ borderColor: "var(--border)", background: "var(--surface-overlay)" }}
        >
          <span
            className="grid h-11 w-11 place-items-center rounded-[var(--radius-md)]"
            style={{ background: "var(--warn-tint)", color: "var(--warn)" }}
          >
            <FileWarning size={20} />
          </span>
          <p className="text-[13px] font-medium" style={{ color: "var(--fg)" }}>
            {model.highRisk ? "高风险类型，仅显示元数据" : "无内置预览"}
          </p>
          <p className="text-[12px]" style={{ color: "var(--fg-muted)" }}>
            该类型不在受控预览白名单内，出于安全只展示元数据（规范 §4.4）。
          </p>
          <div className="mt-1 w-full rounded-[var(--radius)] p-2 text-left" style={{ background: "var(--surface-inset)" }}>
            <DetailField label="类型">{model.typeLabel}</DetailField>
            <DetailField label="大小">{model.sizeLabel}</DetailField>
            <DetailField label="来源">{model.sourceSession}</DetailField>
            <DetailField label="更新">{model.updatedAtLabel}</DetailField>
          </div>
        </div>
      </div>
    );
  }

  if (model.previewKind === "image") {
    return (
      <div className="grid h-full place-items-center">
        {model.preview ? (
          <img
            src={model.preview}
            alt={model.name}
            className="max-h-full max-w-full rounded-[var(--radius-lg)] border object-contain"
            style={{ borderColor: "var(--border)" }}
          />
        ) : (
          <div className="flex flex-col items-center gap-2" style={{ color: "var(--fg-subtle)" }}>
            <ImageIcon size={26} />
            <p className="text-[12px]">图片内容不可用</p>
          </div>
        )}
      </div>
    );
  }

  if (model.previewKind === "markdown") {
    return (
      <div className="chat-markdown select-text mx-auto max-w-2xl text-[13px]" style={{ color: "var(--fg)" }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{model.preview ?? ""}</ReactMarkdown>
      </div>
    );
  }

  return (
    <pre
      className="select-text overflow-auto rounded-[var(--radius)] border p-3 text-[12px] leading-relaxed"
      style={{ borderColor: "var(--border)", background: "var(--surface-inset)", color: "var(--fg)" }}
    >
      <code>{model.preview}</code>
    </pre>
  );
}
