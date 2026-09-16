import { useEffect } from "react";
import { DesktopTitleBar } from "./DesktopTitleBar";
import { GlobalNavRail } from "./GlobalNavRail";
import { ModuleWorkspace } from "../ModuleWorkspace";
import { useApplyTheme } from "@/hooks/useTheme";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useConnection } from "@/stores/connection";
import { purgeLegacyApprovalStorage } from "@/features/approvals/decisions";
import { useAuthLifecycle } from "@/features/connection/useActivate";

/**
 * 桌面四层外壳（规范 §2）：标题栏 / 全局导航栏 / 上下文侧栏 + 主工作区 + 详情面板。
 * 后三层由各模块经 ModuleLayout 组合；此处负责标题栏、导航轨与全局挂载。
 */
export function AppShell() {
  useApplyTheme();
  useHotkeys();
  useAuthLifecycle();
  useEffect(() => {
    try {
      purgeLegacyApprovalStorage(localStorage);
    } catch {
      // WebView 存储不可用时，页面仍使用内存中的短生命周期记录。
    }
  }, []);
  // 连接隔离（G4）：以活动连接 id 作为子树 key，切换连接时整体重挂载各模块页面，
  // 清空页面内的短生命周期状态（如审批本地决策记录、在途流、滚动位置）。
  const connectionId = useConnection((s) => s.activeConnectionId);

  return (
    <div className="flex h-full w-full flex-col" style={{ background: "var(--surface-window)" }}>
      <DesktopTitleBar />
      <div className="flex min-h-0 flex-1">
        <GlobalNavRail />
        <ModuleWorkspace key={connectionId ?? "none"} />
      </div>
    </div>
  );
}
