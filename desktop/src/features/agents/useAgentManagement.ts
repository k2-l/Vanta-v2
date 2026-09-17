import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AgentPatchInput, AgentWire } from "@/contracts/agents";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";

function useAgentContext() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["capabilities", connectionId] });
  return { connectionId, invalidate };
}

export function useRegisterAgent() {
  const { connectionId, invalidate } = useAgentContext();
  return useMutation<AgentWire, unknown, string>({
    mutationFn: (md) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "agents.register", md },
      }) as Promise<AgentWire>,
    onSuccess: invalidate,
  });
}

export function useUpdateAgent() {
  const { connectionId, invalidate } = useAgentContext();
  return useMutation<AgentWire, unknown, { agentId: string; input: AgentPatchInput }>({
    mutationFn: ({ agentId, input }) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "agents.update", agentId, input },
      }) as Promise<AgentWire>,
    onSuccess: invalidate,
  });
}

export function useDeleteAgent() {
  const { connectionId, invalidate } = useAgentContext();
  return useMutation<unknown, unknown, string>({
    mutationFn: (agentId) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "agents.delete", agentId },
      }),
    onSuccess: invalidate,
  });
}
