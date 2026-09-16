/**
 * 激活连接 + 登录——把结果写入全局连接状态（Zustand），凭据留在 Rust。
 */

import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import { useUi } from "@/stores/ui";
import { DEFAULT_CAPABILITIES } from "@/contracts/connection";
import { toClientError } from "@/contracts/errors";

export function queryBelongsToConnection(queryKey: readonly unknown[], connectionId: string): boolean {
  return queryKey.some((part) => part === connectionId);
}

export function useActivateConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const store = useConnection.getState();
      const previousId = store.activeConnectionId;
      if (previousId) {
        const predicate = (query: { queryKey: readonly unknown[] }) =>
          queryBelongsToConnection(query.queryKey, previousId);
        await queryClient.cancelQueries({ predicate });
        queryClient.removeQueries({ predicate });
      }
      if (previousId !== id) {
        useUi.getState().resetSelections();
      }
      // 激活开始即清掉旧认证和能力，避免真实后端握手期间短暂发出带旧权限的请求。
      useConnection.getState().beginActivation(id);
      const session = await ipc("connection_activate", { id });
      return session;
    },
    onSuccess: (session, requestedId) => {
      const store = useConnection.getState();
      // 用户快速连续切换时，迟到的旧连接结果不得覆盖当前连接状态。
      if (store.activeConnectionId !== requestedId) return;
      store.setStatus(session.status);
      store.setAuth(session.auth);
      store.setCapabilities(session.health.capabilities ?? DEFAULT_CAPABILITIES);
      store.setServerVersion(session.health.serverVersion);
      store.setError(undefined);
      void queryClient.invalidateQueries({
        predicate: (query) => queryBelongsToConnection(query.queryKey, requestedId),
      });
    },
    onError: (err, requestedId) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== requestedId) return;
      const e = toClientError(err);
      store.setStatus(e.kind === "offline" ? "offline" : "degraded");
      store.setError(e.message);
    },
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: async (args: { connectionId: string; password: string }) => {
      useConnection.getState().setStatus("authenticating");
      return ipc("auth_login", args);
    },
    onSuccess: (auth, args) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== args.connectionId) return;
      store.setAuth(auth);
      store.setStatus(auth.authenticated ? "online" : "unauthenticated");
      store.setError(undefined);
    },
    onError: (err, args) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== args.connectionId) return;
      const e = toClientError(err);
      store.setStatus(e.kind === "unauthorized" ? "unauthenticated" : "degraded");
      store.setError(e.message);
    },
  });
}

export function useRefreshAuth() {
  return useMutation({
    mutationFn: (connectionId: string) => ipc("auth_refresh", { connectionId }),
    onSuccess: (auth, connectionId) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== connectionId) return;
      store.setAuth(auth);
      store.setStatus("online");
      store.setError(undefined);
    },
    onError: (err, connectionId) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== connectionId) return;
      const error = toClientError(err);
      if (error.kind === "unauthorized") {
        store.setAuth({ authenticated: false });
        store.setStatus("unauthenticated");
      } else {
        store.setStatus("degraded");
      }
      store.setError(error.message);
    },
  });
}

/** 在访问令牌到期前一分钟静默轮换；刷新会话失效时立即回到登录态。 */
export function useAuthLifecycle() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const authenticated = useConnection((state) => state.auth.authenticated);
  const expiresAt = useConnection((state) => state.auth.expiresAt);

  useEffect(() => {
    if (!connectionId || !authenticated || !expiresAt) return;
    const expires = new Date(expiresAt).getTime();
    if (!Number.isFinite(expires)) return;
    const delay = Math.max(0, Math.min(expires - Date.now() - 60_000, 2_147_000_000));
    const timer = window.setTimeout(async () => {
      try {
        const auth = await ipc("auth_refresh", { connectionId });
        const store = useConnection.getState();
        if (store.activeConnectionId !== connectionId) return;
        store.setAuth(auth);
        store.setStatus("online");
        store.setError(undefined);
      } catch (cause) {
        const store = useConnection.getState();
        if (store.activeConnectionId !== connectionId) return;
        const error = toClientError(cause);
        if (error.kind === "unauthorized") {
          store.setAuth({ authenticated: false });
          store.setStatus("unauthenticated");
        } else {
          store.setStatus("degraded");
        }
        store.setError(error.message);
      }
    }, delay);
    return () => window.clearTimeout(timer);
  }, [authenticated, connectionId, expiresAt]);
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (connectionId: string) => ipc("auth_logout", { connectionId }),
    onSuccess: (_, connectionId) => {
      const store = useConnection.getState();
      if (store.activeConnectionId === connectionId) store.setError(undefined);
    },
    onError: (err, connectionId) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== connectionId) return;
      store.setError(`本机登录已清除，但服务端撤销失败：${toClientError(err).message}`);
    },
    onSettled: async (_, _error, connectionId) => {
      const store = useConnection.getState();
      if (store.activeConnectionId !== connectionId) return;
      const predicate = (query: { queryKey: readonly unknown[] }) =>
        queryBelongsToConnection(query.queryKey, connectionId);
      await queryClient.cancelQueries({ predicate });
      queryClient.removeQueries({ predicate });
      useUi.getState().resetSelections();
      store.setAuth({ authenticated: false });
      store.setStatus("unauthenticated");
    },
  });
}
