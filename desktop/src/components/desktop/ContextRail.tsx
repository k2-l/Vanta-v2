/**
 * 上下文侧栏（规范 §2 / §4）——当前模块的对象列表、筛选与局部状态。
 * 固定头部（标题 / 操作 / 搜索 / 筛选）+ 可滚动主体；宽度由 ModuleLayout 控制。
 */

import { useEffect, useRef, type ReactNode } from "react";
import { Search } from "lucide-react";
import { FOCUS_SEARCH_EVENT } from "@/hooks/useHotkeys";

export function ContextRail({
  title,
  action,
  search,
  filters,
  children,
  footer,
}: {
  title: ReactNode;
  /** 头部右侧操作（如新建）。 */
  action?: ReactNode;
  /** 搜索槽——通常放 <RailSearch/>。 */
  search?: ReactNode;
  /** 筛选槽——分段控件或筛选行。 */
  filters?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div
      className="flex h-full min-h-0 flex-col border-r"
      style={{ background: "var(--surface-nav)", borderColor: "var(--border)" }}
    >
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 px-3">
        <h2 className="truncate text-[13px] font-semibold" style={{ color: "var(--fg)" }}>
          {title}
        </h2>
        {action && <div className="no-drag flex shrink-0 items-center gap-1">{action}</div>}
      </div>

      {(search || filters) && (
        <div className="flex shrink-0 flex-col gap-2 px-3 pb-2">
          {search}
          {filters}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">{children}</div>

      {footer && (
        <div className="shrink-0 border-t px-2 py-2" style={{ borderColor: "var(--border)" }}>
          {footer}
        </div>
      )}
    </div>
  );
}

/** 上下文侧栏搜索框——响应 ⌘/Ctrl + K 聚焦（规范 §5）。 */
export function RailSearch({
  value,
  onChange,
  placeholder = "搜索…",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const focus = () => ref.current?.focus();
    window.addEventListener(FOCUS_SEARCH_EVENT, focus);
    return () => window.removeEventListener(FOCUS_SEARCH_EVENT, focus);
  }, []);

  return (
    <div
      className="flex h-8 items-center gap-2 rounded-[var(--radius)] px-2.5"
      style={{ background: "var(--surface-inset)", border: "1px solid var(--border)" }}
    >
      <Search size={14} style={{ color: "var(--fg-subtle)" }} className="shrink-0" />
      <input
        ref={ref}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent text-[12px] outline-none"
        style={{ color: "var(--fg)" }}
      />
    </div>
  );
}

/** 侧栏分组标题（时间分组 / 能力分类）。 */
export function RailGroupLabel({ children }: { children: ReactNode }) {
  return (
    <p
      className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wide"
      style={{ color: "var(--fg-subtle)" }}
    >
      {children}
    </p>
  );
}

/** 侧栏可选项——分类 / 章节导航（比 ResourceRow 更紧凑）。 */
export function RailItem({
  label,
  icon,
  count,
  selected = false,
  onClick,
}: {
  label: ReactNode;
  icon?: ReactNode;
  count?: number | string;
  selected?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      aria-current={selected}
      onClick={onClick}
      className="relative flex h-9 w-full items-center gap-2.5 rounded-[var(--radius)] px-2.5 text-left text-[13px] transition-colors hover:bg-[var(--surface-inset)]"
      style={{
        background: selected ? "var(--accent-tint)" : undefined,
        color: selected ? "var(--fg)" : "var(--fg-muted)",
        fontWeight: selected ? 600 : 500,
      }}
    >
      {icon && (
        <span className="grid shrink-0 place-items-center" style={{ color: selected ? "var(--accent)" : "var(--fg-subtle)" }}>
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== undefined && count !== "" && (
        <span className="shrink-0 text-[11px] tabular-nums" style={{ color: "var(--fg-subtle)" }}>
          {count}
        </span>
      )}
    </button>
  );
}
