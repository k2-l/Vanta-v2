import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageSquare, ShieldCheck } from "lucide-react";
import { Button } from "@/components/Button";
import {
  ModuleLayout,
  ContextRail,
  RailItem,
  ContentHeader,
  DetailToggleButton,
  DetailPanel,
  DetailSection,
  DetailField,
  ApprovalCard,
  StatusBadge,
  EmptyState,
  LoadingState,
  OfflineState,
  type ApprovalCardModel,
} from "@/components/desktop";
import { useUi } from "@/stores/ui";
import { useConnection } from "@/stores/connection";
import { formatRelative } from "@/lib/format";
import type { ApprovalWire } from "@/contracts/resources";
import { approvalRisk, useApprovals, useDecideApproval } from "@/features/approvals/useApprovals";

type Outcome = "approved" | "rejected";
type Decided = { item: ApprovalWire; outcome: Outcome; at: string };

const STATUS_META: Record<"pending" | Outcome, { label: string; tone: "warn" | "ok" | "danger" }> = {
  pending: { label: "待处理", tone: "warn" },
  approved: { label: "已批准", tone: "ok" },
  rejected: { label: "已拒绝", tone: "danger" },
};

export function ApprovalsPage() {
  const connected = useConnection((s) => Boolean(s.activeConnectionId && s.auth.authenticated));
  const offline = useConnection((s) => s.status === "offline");
  const filter = (useUi((s) => s.modules.approvals.filter) ?? "pending") as "pending" | Outcome;
  const setFilter = useUi((s) => s.setFilter);
  const selectedId = useUi((s) => s.modules.approvals.selectedId);
  const select = useUi((s) => s.select);
  const navigate = useNavigate();

  const approvals = useApprovals();
  const decide = useDecideApproval();
  // 本次会话内的决策记录（后端 pending 队列在 resolve 后即消失，历史仅客户端可追溯）。
  const [decided, setDecided] = useState<Decided[]>([]);
  const decidedIds = useMemo(() => new Set(decided.map((d) => d.item.call_id)), [decided]);

  const pending = (approvals.data ?? []).filter((a) => !decidedIds.has(a.call_id));
  const counts = {
    pending: pending.length,
    approved: decided.filter((d) => d.outcome === "approved").length,
    rejected: decided.filter((d) => d.outcome === "rejected").length,
  };

  const onDecide = (item: ApprovalWire, approved: boolean) => {
    decide.mutate(
      { callId: item.call_id, approved },
      {
        onSuccess: (res) => {
          const ok = (res as { ok?: boolean } | null)?.ok;
          if (ok !== false) {
            setDecided((d) => [{ item, outcome: approved ? "approved" : "rejected", at: new Date().toISOString() }, ...d]);
          }
        },
      },
    );
  };

  const toModel = (item: ApprovalWire, status: "pending" | Outcome): ApprovalCardModel => {
    const risk = approvalRisk(item.tool_name);
    const st = STATUS_META[status];
    return {
      id: item.call_id,
      title: item.message || `${item.tool_name} 待授权`,
      source: item.tool_name,
      riskLabel: risk.label,
      riskTone: risk.tone,
      statusLabel: st.label,
      statusTone: st.tone,
      target: `工具 ${item.tool_name}`,
      scope: `会话 ${item.session_id.slice(0, 12)}`,
      impact: "批准后该工具方可执行；拒绝则此次工具调用按失败处理",
      allowLabel: "允许本次",
      requestedAt: item.requested_at,
      expiresAt: item.expires_at,
      isPending: status === "pending",
      selected: selectedId === item.call_id,
    };
  };

  const rail = (
    <ContextRail title="审批">
      <RailItem label="待处理" count={counts.pending} selected={filter === "pending"} onClick={() => setFilter("approvals", "pending")} />
      <RailItem label="已批准" count={counts.approved} selected={filter === "approved"} onClick={() => setFilter("approvals", "approved")} />
      <RailItem label="已拒绝" count={counts.rejected} selected={filter === "rejected"} onClick={() => setFilter("approvals", "rejected")} />
    </ContextRail>
  );

  // 当前分类下要展示的条目。
  const shown: { item: ApprovalWire; status: "pending" | Outcome }[] =
    filter === "pending"
      ? pending.map((item) => ({ item, status: "pending" as const }))
      : decided.filter((d) => d.outcome === filter).map((d) => ({ item: d.item, status: d.outcome }));

  const selected = shown.find((s) => s.item.call_id === selectedId);

  const detail = selected ? (
    <DetailPanel title="审批追溯" onClose={() => useUi.getState().setDetailOpen("approvals", false)}>
      <DetailSection title="状态">
        <div className="flex gap-1.5">
          <StatusBadge tone={approvalRisk(selected.item.tool_name).tone}>{approvalRisk(selected.item.tool_name).label}</StatusBadge>
          <StatusBadge tone={STATUS_META[selected.status].tone}>{STATUS_META[selected.status].label}</StatusBadge>
        </div>
      </DetailSection>
      <DetailSection title="请求">
        <DetailField label="请求 ID"><span className="font-mono text-[11px]">{selected.item.call_id}</span></DetailField>
        <DetailField label="工具">{selected.item.tool_name}</DetailField>
        <DetailField label="发起">{formatRelative(selected.item.requested_at)}</DetailField>
        <DetailField label="到期">{formatRelative(selected.item.expires_at)}</DetailField>
      </DetailSection>
      <DetailSection title="操作说明">
        <p className="select-text text-[12px] leading-relaxed" style={{ color: "var(--fg)" }}>{selected.item.message}</p>
      </DetailSection>
      <Button
        size="sm"
        variant="secondary"
        className="w-full"
        onClick={() => {
          useUi.getState().select("chat", selected.item.session_id);
          navigate("/chat");
        }}
      >
        <MessageSquare size={14} />
        打开来源会话
      </Button>
      <p className="mt-3 text-[11px] leading-relaxed" style={{ color: "var(--fg-subtle)" }}>
        批准与拒绝以 call_id 为幂等键，已处理项不可重复提交（规范 §4.3）。
      </p>
    </DetailPanel>
  ) : undefined;

  return (
    <ModuleLayout module="approvals" rail={rail} detail={detail}>
      <ContentHeader
        title="审批队列"
        subtitle="Human-in-the-loop · 高风险操作需明确授权"
        actions={<DetailToggleButton module="approvals" />}
      />
      {!connected ? (
        offline ? (
          <OfflineState />
        ) : (
          <EmptyState icon={ShieldCheck} title="连接后查看审批" hint="全局待处理审批来自后端 HITL 队列。" />
        )
      ) : approvals.isLoading ? (
        <LoadingState title="加载待处理审批…" />
      ) : shown.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title={filter === "pending" ? "没有待处理的审批" : "本次会话暂无该记录"}
          hint={filter === "pending" ? "工具请求人工确认时会实时出现在这里。" : "已批准 / 已拒绝为本次会话内的决策记录。"}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mx-auto flex max-w-2xl flex-col gap-3">
            {shown.map(({ item, status }) => (
              <ApprovalCard
                key={item.call_id}
                model={toModel(item, status)}
                onSelect={() => select("approvals", item.call_id)}
                onApprove={() => onDecide(item, true)}
                onReject={() => onDecide(item, false)}
              />
            ))}
          </div>
        </div>
      )}
    </ModuleLayout>
  );
}
