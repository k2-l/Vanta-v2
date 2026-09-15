/**
 * 审批卡（规范 §4.3）——必须展示来源、风险、对象、范围与影响。
 * 主按钮文案描述授权范围（如「允许本次」），禁止含糊的「确定」。
 * 过期 / 非待处理时操作禁用，结果需可追溯。纯展示组件，只接收归一化 model。
 */

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/Button";
import { StatusBadge, type Tone } from "./status";
import { formatRelative } from "@/lib/format";

export type ApprovalCardModel = {
  id: string;
  title: string;
  source: string;
  riskLabel: string;
  riskTone: Tone;
  statusLabel: string;
  statusTone: Tone;
  target: string;
  scope: string;
  impact: string;
  allowLabel: string;
  requestedAt: string;
  expiresAt?: string;
  isPending: boolean;
  /** 已过期（超过 expires_at 仍未处理）：与已归档区分文案，操作同样禁用。 */
  expired?: boolean;
  selected?: boolean;
  auditWarning?: string;
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 py-1 text-[12px]">
      <span className="w-14 shrink-0" style={{ color: "var(--fg-subtle)" }}>
        {label}
      </span>
      <span className="min-w-0 flex-1 select-text" style={{ color: "var(--fg)" }}>
        {children}
      </span>
    </div>
  );
}

export function ApprovalCard({
  model,
  onApprove,
  onReject,
  onSelect,
  submitting = false,
  error,
}: {
  model: ApprovalCardModel;
  onApprove?: () => void;
  onReject?: () => void;
  onSelect?: () => void;
  /** 该卡决策提交中：禁用双按钮并在主按钮显示 spinner。 */
  submitting?: boolean;
  /** 决策提交失败原因（含后端返回"已处理/失效"）。 */
  error?: string;
}) {
  const disabled = !model.isPending || submitting;
  return (
    <article
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect?.();
        }
      }}
      tabIndex={onSelect ? 0 : undefined}
      role="group"
      aria-label={`审批：${model.title}`}
      aria-current={model.selected}
      className="rounded-[var(--radius-lg)] border p-4 transition-colors"
      style={{
        background: "var(--surface-overlay)",
        borderColor: model.selected ? "var(--accent)" : "var(--border)",
      }}
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <StatusBadge tone={model.riskTone}>{model.riskLabel}</StatusBadge>
            <StatusBadge tone={model.statusTone}>{model.statusLabel}</StatusBadge>
          </div>
          <h3 className="truncate text-[14px] font-semibold" style={{ color: "var(--fg)" }}>
            {model.title}
          </h3>
        </div>
      </header>

      <div className="mb-3 rounded-[var(--radius)] p-2" style={{ background: "var(--surface-inset)" }}>
        <Row label="来源">{model.source}</Row>
        <Row label="对象">{model.target}</Row>
        <Row label="范围">{model.scope}</Row>
        <Row label="影响">{model.impact}</Row>
      </div>

      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
          {formatRelative(model.requestedAt)}请求
          {model.expiresAt && model.isPending && ` · ${formatRelative(model.expiresAt)}到期`}
          {model.expired && " · 已过期，不可再次提交"}
          {!model.isPending && !model.expired && " · 已归档，不可再次提交"}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            size="sm"
            variant="dangerGhost"
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation();
              onReject?.();
            }}
          >
            拒绝
          </Button>
          <Button
            size="sm"
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation();
              onApprove?.();
            }}
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            {model.allowLabel}
          </Button>
        </div>
      </div>
      {error && (
        <p className="mt-2 text-[11px]" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      {model.auditWarning && (
        <p className="mt-2 text-[11px] leading-relaxed" style={{ color: "var(--warn)" }} role="status">
          {model.auditWarning}
        </p>
      )}
    </article>
  );
}
