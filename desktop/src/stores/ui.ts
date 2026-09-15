/**
 * 桌面 UI 布局状态（规范 §5 / Plan G1.5「模块级布局状态」）。
 *
 * 只承载展示层的短生命周期状态：主题、各模块的详情开关 / 筛选 / 最近选择。
 * 服务端权威状态走 TanStack Query，连接状态走 stores/connection。
 * 切换模块时保留各模块最近选择（规范 §5）。
 */

import { create } from "zustand";

export type ModuleId =
  | "chat"
  | "runs"
  | "approvals"
  | "artifacts"
  | "capabilities"
  | "settings";

export type ThemePref = "dark" | "light" | "system";

type ModuleState = {
  /** 用户对详情面板的意向（最终是否展示还要受窗口断点约束）。 */
  detailOpen: boolean;
  /** 上下文侧栏当前筛选键。 */
  filter: string | null;
  /** 最近选择的对象 id，跨模块切换保留。 */
  selectedId: string | null;
};

const THEME_KEY = "vanta.theme";

function initialTheme(): ThemePref {
  if (typeof localStorage === "undefined") return "dark";
  const raw = localStorage.getItem(THEME_KEY);
  return raw === "light" || raw === "system" || raw === "dark" ? raw : "dark";
}

/** 详情面板默认开启的模块（规范 §2：对话 / 运行 / 审批按需出现）。 */
const DETAIL_DEFAULT: Record<ModuleId, boolean> = {
  chat: true,
  runs: true,
  approvals: true,
  artifacts: false,
  capabilities: false,
  settings: false,
};

function makeModules(): Record<ModuleId, ModuleState> {
  const ids: ModuleId[] = ["chat", "runs", "approvals", "artifacts", "capabilities", "settings"];
  return Object.fromEntries(
    ids.map((id) => [id, { detailOpen: DETAIL_DEFAULT[id], filter: null, selectedId: null }]),
  ) as Record<ModuleId, ModuleState>;
}

interface UiState {
  theme: ThemePref;
  setTheme: (theme: ThemePref) => void;

  modules: Record<ModuleId, ModuleState>;
  setDetailOpen: (module: ModuleId, open: boolean) => void;
  toggleDetail: (module: ModuleId) => void;
  setFilter: (module: ModuleId, filter: string | null) => void;
  select: (module: ModuleId, id: string | null) => void;
  /** 连接切换时清空各模块的对象选择（selectedId 指向具体连接的资源，不可跨连接沿用）。 */
  resetSelections: () => void;
}

export const useUi = create<UiState>((set) => ({
  theme: initialTheme(),
  setTheme: (theme) => {
    if (typeof localStorage !== "undefined") localStorage.setItem(THEME_KEY, theme);
    set({ theme });
  },

  modules: makeModules(),
  setDetailOpen: (module, open) =>
    set((s) => ({ modules: { ...s.modules, [module]: { ...s.modules[module], detailOpen: open } } })),
  toggleDetail: (module) =>
    set((s) => ({
      modules: { ...s.modules, [module]: { ...s.modules[module], detailOpen: !s.modules[module].detailOpen } },
    })),
  setFilter: (module, filter) =>
    set((s) => ({ modules: { ...s.modules, [module]: { ...s.modules[module], filter } } })),
  select: (module, id) =>
    set((s) => ({ modules: { ...s.modules, [module]: { ...s.modules[module], selectedId: id } } })),
  resetSelections: () =>
    set((s) => ({
      modules: Object.fromEntries(
        (Object.keys(s.modules) as ModuleId[]).map((id) => [id, { ...s.modules[id], selectedId: null }]),
      ) as Record<ModuleId, ModuleState>,
    })),
}));
