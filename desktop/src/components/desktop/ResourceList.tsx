/**
 * 高密度资源列表（规范 §3.2 行高 42–52 / §4.2 运行列表）。
 * ResourceRow 是可键盘聚焦的按钮；颜色只作强调，选中态叠加左侧强调线。
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function ResourceList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div role="list" className={cn("flex flex-col", className)}>
      {children}
    </div>
  );
}

export function ResourceRow({
  title,
  subtitle,
  leading,
  meta,
  trailing,
  selected = false,
  dense = false,
  onClick,
  ariaLabel,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** 左侧状态点 / 图标。 */
  leading?: ReactNode;
  /** 右上角元数据（时间 / 数量）。 */
  meta?: ReactNode;
  /** 右侧持续可见的操作或标记。 */
  trailing?: ReactNode;
  selected?: boolean;
  dense?: boolean;
  onClick?: () => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="listitem"
      aria-current={selected}
      aria-label={ariaLabel}
      onClick={onClick}
      className={cn(
        "group relative flex w-full items-center gap-3 rounded-[var(--radius)] px-3 text-left transition-colors",
        "hover:bg-[var(--surface-inset)]",
      )}
      style={{
        minHeight: dense ? "var(--row-h-sm)" : "var(--row-h)",
        background: selected ? "var(--accent-tint)" : undefined,
        paddingTop: 8,
        paddingBottom: 8,
      }}
    >
      {selected && (
        <span
          aria-hidden
          className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full"
          style={{ background: "var(--accent)" }}
        />
      )}
      {leading && <span className="grid shrink-0 place-items-center">{leading}</span>}
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span
            className="min-w-0 flex-1 truncate text-[13px]"
            style={{ color: selected ? "var(--fg)" : "var(--fg)", fontWeight: selected ? 600 : 500 }}
          >
            {title}
          </span>
          {meta && (
            <span className="shrink-0 text-[10px] tabular-nums" style={{ color: "var(--fg-subtle)" }}>
              {meta}
            </span>
          )}
        </span>
        {subtitle && (
          <span className="mt-0.5 block truncate text-[11px]" style={{ color: "var(--fg-muted)" }}>
            {subtitle}
          </span>
        )}
      </span>
      {trailing && <span className="shrink-0">{trailing}</span>}
    </button>
  );
}
