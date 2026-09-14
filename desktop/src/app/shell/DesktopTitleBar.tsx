/**
 * 标题栏（规范 §2 / §4）——工作区身份、活动连接、窗口拖动区域。
 * 整条为拖动区域，交互控件标记 no-drag。凭据永不在此展示。
 */

import { ConnectionStatusBadge } from "@/features/connection/ConnectionStatusBadge";
import { ThemeToggle } from "@/components/desktop/ThemeToggle";

export function DesktopTitleBar() {
  return (
    <header
      className="drag-region flex shrink-0 items-center gap-3 border-b px-3"
      style={{
        height: "var(--titlebar-h)",
        background: "var(--surface-window)",
        borderColor: "var(--border)",
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="grid h-6 w-6 place-items-center rounded-[var(--radius-sm)] text-[13px] font-bold"
          style={{ background: "var(--accent)", color: "var(--accent-fg)" }}
        >
          V
        </span>
        <span className="text-[13px] font-semibold tracking-tight" style={{ color: "var(--fg)" }}>
          Vanta
        </span>
        <span className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
          单兵作战 Agent 平台
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <ConnectionStatusBadge />
        <ThemeToggle />
      </div>
    </header>
  );
}
