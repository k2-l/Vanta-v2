/**
 * 全局导航栏（规范 §2）——58px 图标轨，六个一级模块 + 全局未读状态。
 * 键盘可达：每项是 NavLink（原生链接可聚焦）；未读用角标表达（不仅靠颜色）。
 */

import { NavLink } from "react-router-dom";
import { NAV_ITEMS } from "./nav";
import { cn } from "@/lib/cn";
import type { ModuleId } from "@/stores/ui";
import { useApprovalCount } from "@/features/approvals/useApprovals";

/** 各模块未读角标——approvals 为后端待处理队列的实时数量（未连接时为 0）。 */
function useNavBadges(): Partial<Record<ModuleId, number>> {
  return { approvals: useApprovalCount() };
}

export function GlobalNavRail() {
  const badges = useNavBadges();

  return (
    <nav
      aria-label="主导航"
      className="flex h-full shrink-0 flex-col items-center gap-1 border-r py-2"
      style={{
        width: "var(--nav-rail-w)",
        background: "var(--surface-window)",
        borderColor: "var(--border)",
      }}
    >
      {NAV_ITEMS.map(({ id, to, label, icon: Icon }) => {
        const badge = badges[id];
        return (
          <NavLink
            key={to}
            to={to}
            aria-label={badge ? `${label}（${badge} 待处理）` : label}
            className="group relative flex w-[46px] flex-col items-center gap-1 rounded-[var(--radius)] py-2 transition-colors"
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span
                    aria-hidden
                    className="absolute left-[-6px] top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r-full"
                    style={{ background: "var(--accent)" }}
                  />
                )}
                <span
                  className={cn(
                    "relative grid h-8 w-8 place-items-center rounded-[var(--radius)] transition-colors",
                    !isActive && "group-hover:bg-[var(--surface-inset)]",
                  )}
                  style={{
                    background: isActive ? "var(--accent-tint)" : undefined,
                    color: isActive ? "var(--accent)" : "var(--fg-muted)",
                  }}
                >
                  <Icon size={19} />
                  {badge ? (
                    <span
                      className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full px-1 text-[10px] font-semibold leading-none"
                      style={{ background: "var(--warn)", color: "#1a1205" }}
                    >
                      {badge}
                    </span>
                  ) : null}
                </span>
                <span
                  className="text-[10px] leading-none"
                  style={{ color: isActive ? "var(--fg)" : "var(--fg-subtle)" }}
                >
                  {label}
                </span>
              </>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}
