/**
 * 本地 UI 状态（方案 §12.2）——导航、面板、草稿等非持久 / 弱持久状态。
 * 不承载服务端权威状态（那些走 TanStack Query）。
 */

import { create } from "zustand";

interface UiState {
  sidebarCollapsed: boolean;
  selectedSessionId: string | null;
  selectedRunId: string | null;
  selectedInvocationId: string | null;

  toggleSidebar: () => void;
  selectSession: (id: string | null) => void;
  selectRun: (id: string | null) => void;
  selectInvocation: (id: string | null) => void;
}

export const useUi = create<UiState>((set) => ({
  sidebarCollapsed: false,
  selectedSessionId: null,
  selectedRunId: null,
  selectedInvocationId: null,

  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  selectSession: (selectedSessionId) => set({ selectedSessionId }),
  selectRun: (selectedRunId) => set({ selectedRunId }),
  selectInvocation: (selectedInvocationId) => set({ selectedInvocationId }),
}));
