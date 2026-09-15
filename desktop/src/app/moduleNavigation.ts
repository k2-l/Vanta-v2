import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useUi, type ModuleId } from "@/stores/ui";

export const MODULE_IDS: readonly ModuleId[] = [
  "chat",
  "runs",
  "approvals",
  "artifacts",
  "capabilities",
  "settings",
];

export function modulePath(module: ModuleId): string {
  return `/${module}`;
}

export function moduleFromPath(pathname: string): ModuleId | undefined {
  const segment = pathname.split("/").filter(Boolean)[0];
  return MODULE_IDS.find((module) => module === segment);
}

export function useIsModuleActive(module: ModuleId): boolean {
  return moduleFromPath(useLocation().pathname) === module;
}

type OpenModuleOptions = {
  selectedId?: string | null;
  detailOpen?: boolean;
  state?: unknown;
  replace?: boolean;
};

/** 跨模块跳转的唯一入口：先写目标模块上下文，再切换工作区。 */
export function useModuleNavigation() {
  const navigate = useNavigate();

  return useCallback(
    (module: ModuleId, options: OpenModuleOptions = {}) => {
      if (options.selectedId !== undefined) useUi.getState().select(module, options.selectedId);
      if (options.detailOpen !== undefined) {
        useUi.getState().setDetailOpen(module, options.detailOpen);
      }
      navigate(modulePath(module), { replace: options.replace, state: options.state });
    },
    [navigate],
  );
}
