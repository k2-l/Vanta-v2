/**
 * 全局连接状态（方案 §9.2）——状态机是全局的，侧栏/标题栏/页面统一读取。
 *
 * 只存「当前活动连接」的非敏感投影；凭据、profile 列表分别由 Rust / TanStack Query 管。
 */

import { create } from "zustand";
import type { AuthSummary, ConnectionStatus, ServerCapabilities } from "@/contracts/connection";
import { DEFAULT_CAPABILITIES } from "@/contracts/connection";

interface ConnectionState {
  activeConnectionId: string | null;
  status: ConnectionStatus;
  auth: AuthSummary;
  capabilities: ServerCapabilities;
  serverVersion?: string;
  lastError?: string;

  beginActivation: (id: string) => void;
  setActive: (id: string | null) => void;
  setStatus: (status: ConnectionStatus) => void;
  setAuth: (auth: AuthSummary) => void;
  setCapabilities: (caps: ServerCapabilities) => void;
  setServerVersion: (v?: string) => void;
  setError: (msg?: string) => void;
  reset: () => void;
}

const INITIAL = {
  activeConnectionId: null as string | null,
  status: "unconfigured" as ConnectionStatus,
  auth: { authenticated: false } as AuthSummary,
  capabilities: DEFAULT_CAPABILITIES,
  serverVersion: undefined as string | undefined,
  lastError: undefined as string | undefined,
};

export const useConnection = create<ConnectionState>((set) => ({
  ...INITIAL,
  beginActivation: (activeConnectionId) =>
    set({
      activeConnectionId,
      status: "testing",
      auth: { authenticated: false },
      capabilities: DEFAULT_CAPABILITIES,
      serverVersion: undefined,
      lastError: undefined,
    }),
  setActive: (activeConnectionId) => set({ activeConnectionId }),
  setStatus: (status) => set({ status }),
  setAuth: (auth) => set({ auth }),
  setCapabilities: (capabilities) => set({ capabilities }),
  setServerVersion: (serverVersion) => set({ serverVersion }),
  setError: (lastError) => set({ lastError }),
  reset: () => set({ ...INITIAL }),
}));
