/**
 * 连接管理 hooks——服务端/持有态由 Rust 提供，经 TanStack Query 缓存展示（方案 §12.1）。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import type { ConnectionDraft } from "@/contracts/connection";
import { useConnection } from "@/stores/connection";
import { useUi } from "@/stores/ui";
import { queryBelongsToConnection } from "./useActivate";

const KEY = ["connections"] as const;

export function useConnections() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => ipc("connection_list", undefined),
  });
}

export function useSaveConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ConnectionDraft) => ipc("connection_save", { input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ipc("connection_delete", { id }),
    onSuccess: async (_, id) => {
      if (useConnection.getState().activeConnectionId === id) {
        const predicate = (query: { queryKey: readonly unknown[] }) =>
          queryBelongsToConnection(query.queryKey, id);
        await qc.cancelQueries({ predicate });
        qc.removeQueries({ predicate });
        useUi.getState().resetSelections();
        useConnection.getState().reset();
      }
      await qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (args: { id?: string; draft?: ConnectionDraft }) => ipc("connection_test", args),
  });
}
