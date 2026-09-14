/**
 * 模块布局（规范 §2 / §5）——上下文侧栏 + 主工作区 + 可选详情面板。
 *
 * 断点规则：
 * - 宽度 < 1100：不展示详情面板（即使用户开启）。
 * - 宽度 < 900：压缩上下文侧栏宽度。
 * 详情最终可见 = 提供了 detail 且用户开启且窗口够宽。
 */

import type { ReactNode } from "react";
import { useUi, type ModuleId } from "@/stores/ui";
import { useBreakpoint } from "@/hooks/useBreakpoint";

export function ModuleLayout({
  module,
  rail,
  detail,
  children,
}: {
  module: ModuleId;
  rail: ReactNode;
  detail?: ReactNode;
  children: ReactNode;
}) {
  const detailOpen = useUi((s) => s.modules[module].detailOpen);
  const { canShowDetail, compactRail } = useBreakpoint();
  const showDetail = Boolean(detail) && detailOpen && canShowDetail;

  return (
    <div className="flex h-full min-h-0 w-full">
      <div
        className="h-full shrink-0"
        style={{ width: compactRail ? "var(--context-rail-w-compact)" : "var(--context-rail-w)" }}
      >
        {rail}
      </div>

      <main
        className="flex h-full min-w-0 flex-1 flex-col"
        style={{ minWidth: "var(--content-min-w)", background: "var(--surface-content)" }}
      >
        {children}
      </main>

      {showDetail && (
        <div className="h-full shrink-0" style={{ width: "var(--detail-panel-w)" }}>
          {detail}
        </div>
      )}
    </div>
  );
}
