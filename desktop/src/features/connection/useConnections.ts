/**
 * 连接管理 hooks——服务端/持有态由 Rust 提供，经 TanStack Query 缓存展示（方案 §12.1）。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import type { ConnectionDraft } from "@/contracts/connection";

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
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (args: { id?: string; draft?: ConnectionDraft }) => ipc("connection_test", args),
  });
}
