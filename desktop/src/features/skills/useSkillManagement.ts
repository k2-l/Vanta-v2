import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { SkillPatchInput, SkillWire } from "@/contracts/skills";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";

function useSkillContext() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["capabilities", connectionId] });
  return { connectionId, invalidate };
}

export function useRegisterSkill() {
  const { connectionId, invalidate } = useSkillContext();
  return useMutation<SkillWire, unknown, string>({
    mutationFn: (md) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "skills.register", md },
      }) as Promise<SkillWire>,
    onSuccess: invalidate,
  });
}

export function useUpdateSkill() {
  const { connectionId, invalidate } = useSkillContext();
  return useMutation<SkillWire, unknown, { skillId: string; input: SkillPatchInput }>({
    mutationFn: ({ skillId, input }) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "skills.update", skillId, input },
      }) as Promise<SkillWire>,
    onSuccess: invalidate,
  });
}

export function useDeleteSkill() {
  const { connectionId, invalidate } = useSkillContext();
  return useMutation<unknown, unknown, string>({
    mutationFn: (skillId) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "skills.delete", skillId },
      }),
    onSuccess: invalidate,
  });
}

export function useReindexSkills() {
  const { connectionId, invalidate } = useSkillContext();
  return useMutation<{ reindexed: number; verified: number }, unknown, void>({
    mutationFn: () =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "skills.reindex" },
      }) as Promise<{ reindexed: number; verified: number }>,
    onSuccess: invalidate,
  });
}
