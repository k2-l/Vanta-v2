import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header
      className="flex items-center justify-between h-14 px-6 border-b shrink-0"
      style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}
    >
      <div className="min-w-0">
        <h1 className="text-base font-semibold truncate" style={{ color: "var(--fg)" }}>
          {title}
        </h1>
        {description && (
          <p className="text-xs truncate" style={{ color: "var(--fg-muted)" }}>
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </header>
  );
}
