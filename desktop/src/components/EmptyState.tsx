import type { ReactNode } from "react";

/** 空状态占位——各页在功能补齐前统一呈现（方案 §21：空状态完整）。 */
export function EmptyState({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-6">
      <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>
        {title}
      </p>
      {hint && (
        <p className="text-xs max-w-sm" style={{ color: "var(--fg-muted)" }}>
          {hint}
        </p>
      )}
      {children}
    </div>
  );
}
