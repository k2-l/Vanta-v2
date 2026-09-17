import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { toClientError } from "@/contracts/errors";
import type {
  ContainerProfileInput,
  ContainerProfileWire,
  ContainerReadiness,
  ContainerWire,
  CreateContainerInput,
} from "@/contracts/containers";
import { useConnection } from "@/stores/connection";

function useRuntimeContext() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const queryClient = useQueryClient();
  const invalidate = async (containerId?: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["capabilities", connectionId] }),
      containerId
        ? queryClient.invalidateQueries({ queryKey: ["container-profile", connectionId, containerId] })
        : Promise.resolve(),
      containerId
        ? queryClient.invalidateQueries({ queryKey: ["container-readiness", connectionId, containerId] })
        : Promise.resolve(),
    ]);
  };
  return { connectionId, invalidate };
}

export function useContainerProfile(containerId?: string) {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const authenticated = useConnection((state) => state.auth.authenticated);
  return useQuery<ContainerProfileWire | null>({
    queryKey: ["container-profile", connectionId, containerId],
    enabled: Boolean(connectionId && authenticated && containerId),
    retry: false,
    queryFn: async () => {
      try {
        return (await ipc("api_request", {
          connectionId: connectionId!,
          operation: { op: "containers.profile.get", containerId: containerId! },
        })) as ContainerProfileWire;
      } catch (error) {
        if (toClientError(error).kind === "not_found") return null;
        throw error;
      }
    },
  });
}

export function useContainerReadiness(containerId?: string) {
  const connectionId = useConnection((state) => state.activeConnectionId);
  return useQuery<ContainerReadiness>({
    queryKey: ["container-readiness", connectionId, containerId],
    enabled: false,
    retry: false,
    queryFn: () =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "containers.readiness", containerId: containerId! },
      }) as Promise<ContainerReadiness>,
  });
}

export function useCreateContainer() {
  const { connectionId, invalidate } = useRuntimeContext();
  return useMutation<ContainerWire, unknown, CreateContainerInput>({
    mutationFn: (input) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "containers.create", input },
      }) as Promise<ContainerWire>,
    onSuccess: () => invalidate(),
  });
}

export function useContainerLifecycle() {
  const { connectionId, invalidate } = useRuntimeContext();
  return useMutation<ContainerWire | null, unknown, { containerId: string; action: "start" | "stop" | "delete" }>({
    mutationFn: ({ containerId, action }) => {
      const operation = action === "start"
        ? { op: "containers.start" as const, containerId }
        : action === "stop"
          ? { op: "containers.stop" as const, containerId }
          : { op: "containers.delete" as const, containerId };
      return ipc("api_request", {
        connectionId: connectionId!,
        operation,
      }) as Promise<ContainerWire | null>;
    },
    onSuccess: (_, variables) => invalidate(variables.containerId),
  });
}

export function useSaveContainerProfile() {
  const { connectionId, invalidate } = useRuntimeContext();
  return useMutation<ContainerProfileWire, unknown, { containerId: string; input: ContainerProfileInput }>({
    mutationFn: ({ containerId, input }) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "containers.profile.put", containerId, input },
      }) as Promise<ContainerProfileWire>,
    onSuccess: (_, variables) => invalidate(variables.containerId),
  });
}

export function useDeleteContainerProfile() {
  const { connectionId, invalidate } = useRuntimeContext();
  return useMutation<unknown, unknown, string>({
    mutationFn: (containerId) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "containers.profile.delete", containerId },
      }),
    onSuccess: (_, containerId) => invalidate(containerId),
  });
}
