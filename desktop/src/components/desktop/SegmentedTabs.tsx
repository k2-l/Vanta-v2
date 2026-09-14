/**
 * 水平分段控件——上下文侧栏里的状态 / 范围筛选（规范 §4.2 / §4.3）。
 * 键盘可达：每段是按钮，选中态用强调背景 + aria-pressed 表达。
 */

import { cn } from "@/lib/cn";

export type SegmentItem = {
  key: string;
  label: string;
  count?: number;
};

export function SegmentedTabs({
  items,
  value,
  onChange,
  className,
}: {
  items: SegmentItem[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn("flex gap-1 rounded-[var(--radius)] p-0.5", className)}
      style={{ background: "var(--surface-inset)" }}
    >
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.key)}
            className="flex h-7 flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-sm)] text-[12px] font-medium transition-colors"
            style={{
              background: active ? "var(--surface-overlay)" : "transparent",
              color: active ? "var(--fg)" : "var(--fg-muted)",
              boxShadow: active ? "var(--shadow-sm)" : undefined,
            }}
          >
            <span className="truncate">{item.label}</span>
            {typeof item.count === "number" && (
              <span
                className="rounded-full px-1 text-[10px] tabular-nums"
                style={{
                  background: active ? "var(--accent-tint)" : "transparent",
                  color: active ? "var(--accent)" : "var(--fg-subtle)",
                }}
              >
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
