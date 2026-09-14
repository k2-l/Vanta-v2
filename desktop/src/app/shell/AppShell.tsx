import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/cn";
import { NAV_ITEMS } from "./nav";
import { ConnectionStatusBadge } from "@/features/connection/ConnectionStatusBadge";
import { useUi } from "@/stores/ui";

/**
 * 应用壳：左侧全局导航 + 顶部全局连接状态 + 内容区。
 * 连接/离线/待审批等全局状态在此统一呈现（方案 §9.2 / §21）。
 */
export function AppShell() {
  const collapsed = useUi((s) => s.sidebarCollapsed);
  const toggle = useUi((s) => s.toggleSidebar);

  return (
    <div className="flex h-full w-full">
      <aside
        className={cn(
          "flex flex-col border-r shrink-0 transition-all",
          collapsed ? "w-[64px]" : "w-[216px]",
        )}
        style={{ background: "var(--bg-elevated)", borderColor: "var(--border)" }}
      >
        <button
          onClick={toggle}
          className="flex items-center gap-2 h-14 px-4 text-left font-semibold shrink-0"
          style={{ color: "var(--fg)" }}
        >
          <span
            className="grid place-items-center w-7 h-7 rounded-md text-sm"
            style={{ background: "var(--accent)", color: "var(--accent-fg)" }}
          >
            V
          </span>
          {!collapsed && <span>Vanta</span>}
        </button>

        <nav className="flex flex-col gap-1 px-2 py-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 h-10 px-3 rounded-md text-sm transition-colors",
                  isActive ? "font-medium" : "hover:opacity-80",
                )
              }
              style={({ isActive }) => ({
                background: isActive ? "var(--bg-inset)" : "transparent",
                color: isActive ? "var(--fg)" : "var(--fg-muted)",
              })}
            >
              <Icon size={18} className="shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto p-2">
          <ConnectionStatusBadge collapsed={collapsed} />
        </div>
      </aside>

      <main className="flex-1 min-w-0 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
