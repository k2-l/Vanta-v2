/**
 * 审批卡（规范 §4.3）——必须展示来源、风险、对象、范围与影响。
 * 主按钮文案描述授权范围（如「允许本次」），禁止含糊的「确定」。
 * 过期 / 非待处理时操作禁用，结果需可追溯。纯展示组件，只接收归一化 model。
 */

import type { ReactNode } from "react";
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
  selected?: boolean;
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
}: {
  model: ApprovalCardModel;
  onApprove?: () => void;
  onReject?: () => void;
  onSelect?: () => void;
}) {
  return (
    <article
      onClick={onSelect}
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
          {!model.isPending && " · 已归档，不可再次提交"}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            size="sm"
            variant="dangerGhost"
            disabled={!model.isPending}
            onClick={(e) => {
              e.stopPropagation();
              onReject?.();
            }}
          >
            拒绝
          </Button>
          <Button
            size="sm"
            disabled={!model.isPending}
            onClick={(e) => {
              e.stopPropagation();
              onApprove?.();
            }}
          >
            {model.allowLabel}
          </Button>
        </div>
      </div>
    </article>
  );
}
