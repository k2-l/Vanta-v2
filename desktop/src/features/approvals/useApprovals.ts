/**
 * 审批数据层（Plan G3）——全局待处理队列轮询 + 决策。
 * 后端 `_pending` 为进程内内存队列；决策以 call_id 作天然幂等键：
 * resolve_approval 对已处理项返回失败，避免重复提交。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import type { ApprovalWire } from "@/contracts/resources";
import type { Tone } from "@/components/desktop/status";

const approvalsKey = (connectionId: string | null) => ["approvals", connectionId] as const;

export function useApprovals() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  return useQuery<ApprovalWire[]>({
    queryKey: approvalsKey(connectionId),
    enabled: Boolean(connectionId && authed),
    refetchInterval: 4000, // 待处理队列是短生命周期的内存态，轮询保持新鲜。
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "approvals.list" },
      });
      return Array.isArray(result) ? (result as ApprovalWire[]) : [];
    },
  });
}

/** 全局待处理数量——导航轨未读角标与审批页共用同一查询缓存。 */
export function useApprovalCount(): number {
  return useApprovals().data?.length ?? 0;
}

export function useDecideApproval() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { callId: string; approved: boolean }) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "approvals.decide", callId: v.callId, approved: v.approved },
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: approvalsKey(connectionId) }),
  });
}

/**
 * 从工具名启发式推断风险等级（后端审批仅含 tool_name + message，无显式风险字段）。
 * 仅作粗分级并如实标注；精确风险/范围/影响需后端在审批请求中携带（未来增量）。
 */
export function approvalRisk(tool: string): { label: string; tone: Tone } {
  const aggressive = /exec|shell|cmd|sql|nmap|sqlmap|exploit|delet|(^|_)rm|write|deploy|upload|curl|http|fetch|request|scan/i;
  return aggressive.test(tool)
    ? { label: "高风险", tone: "danger" }
    : { label: "需确认", tone: "warn" };
}
