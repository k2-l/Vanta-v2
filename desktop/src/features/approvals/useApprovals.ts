/**
 * 审批数据层（Plan G3）——全局待处理队列轮询 + 决策。
 * 后端 `_pending` 为进程内内存队列；决策以 call_id 作天然幂等键：
 * resolve_approval 对已处理项返回失败，避免重复提交。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import type {
  ApprovalDecisionRecord,
  ApprovalDecisionResult,
  ApprovalWire,
} from "@/contracts/resources";
import type { Tone } from "@/components/desktop/status";

const approvalsKey = (connectionId: string | null) => ["approvals", connectionId] as const;
const historyKey = (connectionId: string | null) => ["approvals", "history", connectionId] as const;

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

/**
 * 审批决策历史（GET /chat/approvals/history）——服务端哈希链审计账本的权威记录，
 * 进程重启后仍可查询（区别于本次页面会话的内存乐观记录，见 decisions.ts）。
 */
export function useApprovalHistory() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  return useQuery<ApprovalDecisionRecord[]>({
    queryKey: historyKey(connectionId),
    enabled: Boolean(connectionId && authed),
    staleTime: 10_000,
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "approvals.history" },
      });
      return Array.isArray(result) ? (result as ApprovalDecisionRecord[]) : [];
    },
  });
}

export function useDecideApproval() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const qc = useQueryClient();
  return useMutation<ApprovalDecisionResult, unknown, { callId: string; approved: boolean }>({
    mutationFn: (v) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "approvals.decide", callId: v.callId, approved: v.approved },
      }) as Promise<ApprovalDecisionResult>,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: approvalsKey(connectionId) });
      qc.invalidateQueries({ queryKey: historyKey(connectionId) });
    },
  });
}

const RISK_META: Record<string, { label: string; tone: Tone }> = {
  critical: { label: "严重", tone: "danger" },
  high: { label: "高风险", tone: "danger" },
  medium: { label: "中风险", tone: "warn" },
  low: { label: "低风险", tone: "ok" },
};

/**
 * 后端权威风险等级 → 展示标签/色调。派生风险（risk_source="derived"）如实标注"（派生）"，
 * 不伪称是工具声明（规范 §4.3）。字段缺失（老后端）时回退到中性"需确认"。
 */
export function riskMeta(risk?: string, source?: string): { label: string; tone: Tone } {
  const base = (risk ? RISK_META[risk] : undefined) ?? { label: "需确认", tone: "warn" as Tone };
  return source === "derived" ? { label: `${base.label}（派生）`, tone: base.tone } : base;
}
