import { Outlet } from "react-router-dom";
import { DesktopTitleBar } from "./DesktopTitleBar";
import { GlobalNavRail } from "./GlobalNavRail";
import { useApplyTheme } from "@/hooks/useTheme";
import { useHotkeys } from "@/hooks/useHotkeys";

/**
 * 桌面四层外壳（规范 §2）：标题栏 / 全局导航栏 / 上下文侧栏 + 主工作区 + 详情面板。
 * 后三层由各模块经 ModuleLayout 组合；此处负责标题栏、导航轨与全局挂载。
 */
export function AppShell() {
  useApplyTheme();
  useHotkeys();

  return (
    <div className="flex h-full w-full flex-col" style={{ background: "var(--surface-window)" }}>
      <DesktopTitleBar />
      <div className="flex min-h-0 flex-1">
        <GlobalNavRail />
        <div className="min-w-0 flex-1 overflow-hidden">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
