import {
  lazy,
  Suspense,
  useEffect,
  useState,
  type ComponentType,
  type LazyExoticComponent,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { MODULE_IDS, moduleFromPath, modulePath } from "./moduleNavigation";
import type { ModuleId } from "@/stores/ui";

const MODULE_PAGES: Record<ModuleId, LazyExoticComponent<ComponentType>> = {
  chat: lazy(() => import("@/pages/chat").then((module) => ({ default: module.ChatPage }))),
  runs: lazy(() => import("@/pages/runs").then((module) => ({ default: module.RunsPage }))),
  approvals: lazy(() =>
    import("@/pages/approvals").then((module) => ({ default: module.ApprovalsPage })),
  ),
  artifacts: lazy(() =>
    import("@/pages/artifacts").then((module) => ({ default: module.ArtifactsPage })),
  ),
  capabilities: lazy(() =>
    import("@/pages/capabilities").then((module) => ({ default: module.CapabilitiesPage })),
  ),
  settings: lazy(() =>
    import("@/pages/settings").then((module) => ({ default: module.SettingsPage })),
  ),
};

function ModuleLoading() {
  return (
    <div
      className="grid h-full place-items-center text-[12px]"
      style={{ color: "var(--fg-muted)" }}
      role="status"
    >
      正在打开模块…
    </div>
  );
}

/**
 * 已访问模块保留挂载：切换模块不会丢草稿、筛选、滚动位置或中断对话流。
 * 外层以 connectionId 为 key，只有切换服务器时才销毁整组页面与订阅。
 */
export function ModuleWorkspace() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeModule = moduleFromPath(location.pathname) ?? "chat";
  const [visited, setVisited] = useState<Set<ModuleId>>(() => new Set([activeModule]));

  useEffect(() => {
    if (!moduleFromPath(location.pathname)) {
      navigate(modulePath("chat"), { replace: true });
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    setVisited((current) => {
      if (current.has(activeModule)) return current;
      return new Set([...current, activeModule]);
    });
  }, [activeModule]);

  return (
    <div className="relative h-full min-w-0 flex-1 overflow-hidden">
      {MODULE_IDS.map((module) => {
        if (!visited.has(module)) return null;
        const Page = MODULE_PAGES[module];
        const active = module === activeModule;
        return (
          <div
            key={module}
            data-module={module}
            data-module-active={active ? "true" : "false"}
            aria-hidden={!active}
            className={active ? "h-full min-w-0" : "hidden"}
          >
            <Suspense fallback={<ModuleLoading />}>
              <Page />
            </Suspense>
          </div>
        );
      })}
    </div>
  );
}
