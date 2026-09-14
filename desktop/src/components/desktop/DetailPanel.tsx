/**
 * 详情面板（规范 §2 / §4.1）——运行轨迹、元数据、上下文用量与关联产物。
 * 可关闭；Esc 亦可关闭（全局快捷键）。宽度由 ModuleLayout 控制。
 */

import type { ReactNode } from "react";
import { X } from "lucide-react";

export function DetailPanel({
  title,
  onClose,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <aside
      aria-label="详情面板"
      className="flex h-full min-h-0 flex-col border-l"
      style={{ background: "var(--surface-nav)", borderColor: "var(--border)" }}
    >
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 px-3">
        <h2 className="truncate text-[13px] font-semibold" style={{ color: "var(--fg)" }}>
          {title}
        </h2>
        <button
          type="button"
          aria-label="关闭详情"
          onClick={onClose}
          className="grid h-7 w-7 place-items-center rounded-[var(--radius-sm)] transition-colors hover:bg-[var(--surface-inset)]"
          style={{ color: "var(--fg-muted)" }}
        >
          <X size={15} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">{children}</div>
    </aside>
  );
}

/** 详情面板里的小节标题。 */
export function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-4">
      <p
        className="mb-2 text-[10px] font-semibold uppercase tracking-wide"
        style={{ color: "var(--fg-subtle)" }}
      >
        {title}
      </p>
      {children}
    </section>
  );
}

/** 键值行——详情面板中的元数据展示。 */
export function DetailField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1 text-[12px]">
      <span className="shrink-0" style={{ color: "var(--fg-muted)" }}>
        {label}
      </span>
      <span className="min-w-0 truncate text-right" style={{ color: "var(--fg)" }}>
        {children}
      </span>
    </div>
  );
}
