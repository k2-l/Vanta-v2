/**
 * 激活连接 + 登录——把结果写入全局连接状态（Zustand），凭据留在 Rust。
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import { useUi } from "@/stores/ui";
import { DEFAULT_CAPABILITIES } from "@/contracts/connection";
import { toClientError } from "@/contracts/errors";

export function useActivateConnection() {
  const store = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      // 连接隔离（规范 §4.6 / G4）：切到不同连接前，清空跨连接不可沿用的对象选择，
      // 并移除上一连接的缓存查询与在途订阅，避免旧数据/选择泄漏到新连接。
      if (store.activeConnectionId && store.activeConnectionId !== id) {
        useUi.getState().resetSelections();
        queryClient.removeQueries();
      }
      store.setActive(id);
      store.setStatus("testing");
      const session = await ipc("connection_activate", { id });
      return session;
    },
    onSuccess: (session) => {
      store.setStatus(session.status);
      store.setAuth(session.auth);
      store.setCapabilities(session.health.capabilities ?? DEFAULT_CAPABILITIES);
      store.setServerVersion(session.health.serverVersion);
      store.setError(undefined);
    },
    onError: (err) => {
      const e = toClientError(err);
      store.setStatus(e.kind === "offline" ? "offline" : "degraded");
      store.setError(e.message);
    },
  });
}

export function useLogin() {
  const store = useConnection();
  return useMutation({
    mutationFn: async (args: { connectionId: string; password: string }) => {
      store.setStatus("authenticating");
      return ipc("auth_login", args);
    },
    onSuccess: (auth) => {
      store.setAuth(auth);
      store.setStatus(auth.authenticated ? "online" : "unauthenticated");
    },
    onError: (err) => {
      const e = toClientError(err);
      store.setStatus(e.kind === "unauthorized" ? "unauthenticated" : "degraded");
      store.setError(e.message);
    },
  });
}

export function useLogout() {
  const store = useConnection();
  return useMutation({
    mutationFn: (connectionId: string) => ipc("auth_logout", { connectionId }),
    onSuccess: () => {
      store.setAuth({ authenticated: false });
      store.setStatus("unauthenticated");
    },
  });
}
