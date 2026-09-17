import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  McpServerCreateInput,
  McpServerPatchInput,
  McpServerWire,
  McpTestResult,
} from "@/contracts/mcp";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";

function useMcpContext() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const queryClient = useQueryClient();
  const invalidate = (name?: string) => {
    void queryClient.invalidateQueries({ queryKey: ["capabilities", connectionId] });
    if (name) void queryClient.invalidateQueries({ queryKey: ["mcp-server", connectionId, name] });
  };
  return { connectionId, queryClient, invalidate };
}

export function useMcpServer(name?: string) {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const authed = useConnection((state) => state.auth.authenticated);
  return useQuery<McpServerWire>({
    queryKey: ["mcp-server", connectionId, name],
    enabled: Boolean(connectionId && authed && name),
    queryFn: () =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "mcp.get", name: name! },
      }) as Promise<McpServerWire>,
  });
}

export function useCreateMcpServer() {
  const { connectionId, invalidate } = useMcpContext();
  return useMutation<McpServerWire, unknown, McpServerCreateInput>({
    mutationFn: (input) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "mcp.create", input },
      }) as Promise<McpServerWire>,
    onSuccess: (server) => invalidate(server.name),
  });
}

export function useUpdateMcpServer() {
  const { connectionId, invalidate } = useMcpContext();
  return useMutation<McpServerWire, unknown, { name: string; input: McpServerPatchInput }>({
    mutationFn: ({ name, input }) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "mcp.update", name, input },
      }) as Promise<McpServerWire>,
    onSuccess: (server) => invalidate(server.name),
  });
}

export function useDeleteMcpServer() {
  const { connectionId, queryClient, invalidate } = useMcpContext();
  return useMutation<unknown, unknown, string>({
    mutationFn: (name) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "mcp.delete", name },
      }),
    onSuccess: (_, name) => {
      queryClient.removeQueries({ queryKey: ["mcp-server", connectionId, name] });
      invalidate();
    },
  });
}

export function useTestMcpServer() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  return useMutation<McpTestResult, unknown, string>({
    mutationFn: (name) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "mcp.test", name },
      }) as Promise<McpTestResult>,
  });
}
