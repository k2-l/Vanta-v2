/**
 * 主工作区头部（规范 §4）——当前对象标题 + 操作区。
 * DetailToggleButton 与详情面板联动，窗口过窄（< 1100）时自动禁用（规范 §5）。
 */

import type { ReactNode } from "react";
import { PanelRight } from "lucide-react";
import { useUi, type ModuleId } from "@/stores/ui";
import { useBreakpoint } from "@/hooks/useBreakpoint";

export function ContentHeader({
  title,
  subtitle,
  leading,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** 标题前的状态点 / 图标。 */
  leading?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header
      className="drag-region flex h-12 shrink-0 items-center gap-3 border-b px-4"
      style={{ borderColor: "var(--border)", background: "var(--surface-content)" }}
    >
      {leading && <span className="no-drag shrink-0">{leading}</span>}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold leading-tight" style={{ color: "var(--fg)" }}>
          {title}
        </h1>
        {subtitle && (
          <p className="truncate text-[11px] leading-tight" style={{ color: "var(--fg-muted)" }}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="no-drag flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

/** 详情面板开关——放在 ContentHeader 的 actions 中。 */
export function DetailToggleButton({ module }: { module: ModuleId }) {
  const open = useUi((s) => s.modules[module].detailOpen);
  const toggle = useUi((s) => s.toggleDetail);
  const { canShowDetail } = useBreakpoint();

  const disabled = !canShowDetail;
  return (
    <button
      type="button"
      aria-label={open ? "隐藏详情面板" : "显示详情面板"}
      aria-pressed={open && !disabled}
      disabled={disabled}
      title={disabled ? "窗口过窄，详情面板已收起" : open ? "隐藏详情面板" : "显示详情面板"}
      onClick={() => toggle(module)}
      className="grid h-8 w-8 place-items-center rounded-[var(--radius-sm)] transition-colors hover:bg-[var(--surface-inset)] disabled:opacity-40"
      style={{
        color: open && !disabled ? "var(--accent)" : "var(--fg-muted)",
        background: open && !disabled ? "var(--accent-tint)" : undefined,
      }}
    >
      <PanelRight size={16} />
    </button>
  );
}
