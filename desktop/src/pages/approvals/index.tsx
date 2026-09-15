import { useEffect, useMemo, useRef, useState } from "react";
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
  ErrorState,
  ForbiddenState,
  type ApprovalCardModel,
} from "@/components/desktop";
import type { Tone } from "@/components/desktop";
import { useUi } from "@/stores/ui";
import { useConnection } from "@/stores/connection";
import { formatRelative } from "@/lib/format";
import { toClientError } from "@/contracts/errors";
import type { ApprovalDecisionRecord, ApprovalWire } from "@/contracts/resources";
import {
  isApprovalExpired,
  riskMeta,
  useApprovalHistory,
  useApprovals,
  useDecideApproval,
} from "@/features/approvals/useApprovals";
import { useDecisionLog, type Decision, type DecisionOutcome } from "@/features/approvals/decisions";
import { useModuleNavigation } from "@/app/moduleNavigation";

type Category = "pending" | DecisionOutcome | "expired";
type HistoricalOutcome = Exclude<Category, "pending">;

/** 归一化的已决策视图：服务端历史与本机记录合并后的统一形状。 */
type DecidedView = {
  item: ApprovalWire;
  outcome: HistoricalOutcome;
  decidedAt: string;
  source: "server" | "local";
  decisionId?: string;
  entryHash?: string;
  auditRecorded?: boolean;
};

/** 服务端决策历史项 → 归一化视图（无原始 requested_at，用决策时间近似展示）。 */
function fromRecord(r: ApprovalDecisionRecord): DecidedView {
  return {
    item: {
      call_id: r.call_id,
      tool_name: r.tool_name,
      message: r.message ?? "",
      session_id: r.session_id,
      requested_at: r.requested_at || r.decided_at,
      expires_at: r.expires_at || "",
      risk: r.risk,
      risk_source: r.risk_source,
      target: r.target,
      scope: r.scope,
      impact: r.impact,
    },
    outcome: r.decision,
    decidedAt: r.decided_at,
    source: "server",
    decisionId: r.decision_id,
    entryHash: r.entry_hash,
    auditRecorded: r.audit_recorded,
  };
}

/** 本机记录 → 归一化视图。 */
function fromLocal(d: Decision): DecidedView {
  return {
    item: d.item,
    outcome: d.outcome,
    decidedAt: d.at,
    source: "local",
    decisionId: d.decisionId,
    entryHash: d.entryHash,
    auditRecorded: d.auditRecorded,
  };
}

const STATUS_META: Record<Category, { label: string; tone: Tone }> = {
  pending: { label: "待处理", tone: "warn" },
  approved: { label: "已批准", tone: "ok" },
  rejected: { label: "已拒绝", tone: "danger" },
  expired: { label: "已过期", tone: "neutral" },
};

const EMPTY_COPY: Record<Category, { title: string; hint: string }> = {
  pending: { title: "没有待处理的审批", hint: "工具请求人工确认时会实时出现在这里。" },
  approved: { title: "暂无已批准记录", hint: "已批准来自服务端审计账本，含本次页面会话刚提交的记录。" },
  rejected: { title: "暂无已拒绝记录", hint: "已拒绝来自服务端审计账本，含本次页面会话刚提交的记录。" },
  expired: { title: "没有已过期的审批", hint: "超过到期时间仍未处理的审批会归入此处，不可再提交。" },
};

export function ApprovalsPage() {
  const connected = useConnection((s) => Boolean(s.activeConnectionId && s.auth.authenticated));
  const offline = useConnection((s) => s.status === "offline");
  const connectionId = useConnection((s) => s.activeConnectionId);
  const filter = (useUi((s) => s.modules.approvals.filter) ?? "pending") as Category;
  const setFilter = useUi((s) => s.setFilter);
  const selectedId = useUi((s) => s.modules.approvals.selectedId);
  const select = useUi((s) => s.select);
  const openModule = useModuleNavigation();

  const approvals = useApprovals();
  const history = useApprovalHistory();
  const decide = useDecideApproval();
  const { decisions, record } = useDecisionLog(connectionId);

  // 合并服务端权威历史与本次页面会话的内存记录：按 call_id 去重，服务端优先。
  const decidedViews = useMemo<DecidedView[]>(() => {
    const byId = new Map<string, DecidedView>();
    for (const d of decisions) byId.set(d.item.call_id, fromLocal(d));
    for (const r of history.data ?? []) byId.set(r.call_id, fromRecord(r));
    return [...byId.values()].sort((a, b) => b.decidedAt.localeCompare(a.decidedAt));
  }, [decisions, history.data]);
  const decidedIds = useMemo(
    () => new Set(decidedViews.map((d) => d.item.call_id)),
    [decidedViews],
  );

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);

  const inFlight = useRef(new Set<string>());
  const [submittingIds, setSubmittingIds] = useState<Set<string>>(() => new Set());
  const [decideErrors, setDecideErrors] = useState<Record<string, string>>({});

  const undecided = (approvals.data ?? []).filter((a) => !decidedIds.has(a.call_id));
  const pending = undecided.filter((a) => !isApprovalExpired(a, now));
  const expired = undecided.filter((a) => isApprovalExpired(a, now));
  const expiredHistory = decidedViews.filter((d) => d.outcome === "expired");
  const counts = {
    pending: pending.length,
    approved: decidedViews.filter((d) => d.outcome === "approved").length,
    rejected: decidedViews.filter((d) => d.outcome === "rejected").length,
    expired: expired.length + expiredHistory.length,
  };

  const onDecide = async (item: ApprovalWire, approved: boolean) => {
    if (isApprovalExpired(item, Date.now())) return; // 兜底：过期项禁止提交。
    if (inFlight.current.has(item.call_id)) return;
    inFlight.current.add(item.call_id);
    setSubmittingIds((prev) => new Set(prev).add(item.call_id));
    setDecideErrors((prev) => {
      const next = { ...prev };
      delete next[item.call_id];
      return next;
    });
    try {
      const res = await decide.mutateAsync({ callId: item.call_id, approved });
      if (useConnection.getState().activeConnectionId !== connectionId) return;
      if (res?.ok !== true) {
        setDecideErrors((prev) => ({ ...prev, [item.call_id]: "该请求已被处理或已失效，无法重复提交。" }));
        return;
      }
      record({
        item,
        outcome: res.decision,
        at: new Date().toISOString(),
        decisionId: res.decision_id,
        auditRecorded: res.audit_recorded,
        entryHash: res.entry_hash,
      });
    } catch (e) {
      if (useConnection.getState().activeConnectionId === connectionId) {
        setDecideErrors((prev) => ({ ...prev, [item.call_id]: toClientError(e).message }));
      }
    } finally {
      inFlight.current.delete(item.call_id);
      setSubmittingIds((prev) => {
        const next = new Set(prev);
        next.delete(item.call_id);
        return next;
      });
    }
  };

  const toModel = (item: ApprovalWire, status: Category): ApprovalCardModel => {
    const risk = riskMeta(item.risk, item.risk_source);
    const st = STATUS_META[status];
    return {
      id: item.call_id,
      title: item.message || `${item.tool_name} 待授权`,
      source: item.tool_name,
      riskLabel: risk.label,
      riskTone: risk.tone,
      statusLabel: st.label,
      statusTone: st.tone,
      target: item.target || `工具 ${item.tool_name}`,
      scope: item.scope || `会话 ${item.session_id.slice(0, 12)}`,
      impact: item.impact || "批准后该工具方可执行；拒绝则此次工具调用按失败处理",
      allowLabel: "允许本次",
      requestedAt: item.requested_at,
      expiresAt: item.expires_at,
      isPending: status === "pending",
      expired: status === "expired",
      selected: selectedId === item.call_id,
      auditWarning: decidedViews.find((d) => d.item.call_id === item.call_id)?.auditRecorded === false
        ? "决策已生效，但服务端审计未入账；本次记录仅在当前页面会话可见。"
        : undefined,
    };
  };

  const rail = (
    <ContextRail title="审批">
      <RailItem label="待处理" count={counts.pending} selected={filter === "pending"} onClick={() => setFilter("approvals", "pending")} />
      <RailItem label="已批准" count={counts.approved} selected={filter === "approved"} onClick={() => setFilter("approvals", "approved")} />
      <RailItem label="已拒绝" count={counts.rejected} selected={filter === "rejected"} onClick={() => setFilter("approvals", "rejected")} />
      <RailItem label="已过期" count={counts.expired} selected={filter === "expired"} onClick={() => setFilter("approvals", "expired")} />
    </ContextRail>
  );

  const shown: { item: ApprovalWire; status: Category }[] =
    filter === "pending"
      ? pending.map((item) => ({ item, status: "pending" as const }))
      : filter === "expired"
        ? [
            ...expiredHistory.map((d) => ({ item: d.item, status: "expired" as const })),
            ...expired.map((item) => ({ item, status: "expired" as const })),
          ]
        : decidedViews
            .filter((d) => d.outcome === filter)
            .map((d) => ({ item: d.item, status: d.outcome as Category }));

  const selected = shown.find((s) => s.item.call_id === selectedId);
  const selectedRisk = selected ? riskMeta(selected.item.risk, selected.item.risk_source) : null;
  const selectedDecided = decidedViews.find((d) => d.item.call_id === selectedId);

  const detail = selected && selectedRisk ? (
    <DetailPanel title="审批追溯" onClose={() => useUi.getState().setDetailOpen("approvals", false)}>
      <DetailSection title="状态">
        <div className="flex gap-1.5">
          <StatusBadge tone={selectedRisk.tone}>{selectedRisk.label}</StatusBadge>
          <StatusBadge tone={STATUS_META[selected.status].tone}>{STATUS_META[selected.status].label}</StatusBadge>
        </div>
      </DetailSection>
      <DetailSection title="请求">
        <DetailField label="请求 ID"><span className="font-mono text-[11px]">{selected.item.call_id}</span></DetailField>
        <DetailField label="工具">{selected.item.tool_name}</DetailField>
        <DetailField label="发起">{formatRelative(selected.item.requested_at)}</DetailField>
        {selected.status === "pending" && (
          <DetailField label="到期">{formatRelative(selected.item.expires_at)}</DetailField>
        )}
      </DetailSection>
      <DetailSection title="操作">
        <DetailField label="对象">{selected.item.target || `工具 ${selected.item.tool_name}`}</DetailField>
        <DetailField label="范围">{selected.item.scope || `会话 ${selected.item.session_id.slice(0, 12)}`}</DetailField>
        <DetailField label="影响">{selected.item.impact || "批准后该工具方可执行"}</DetailField>
      </DetailSection>
      <DetailSection title="操作说明">
        <p className="select-text text-[12px] leading-relaxed" style={{ color: "var(--fg)" }}>{selected.item.message}</p>
      </DetailSection>
      {selectedDecided && (
        <DetailSection title="审计证据">
          <DetailField label="决策 ID"><span className="font-mono text-[11px]">{selectedDecided.decisionId}</span></DetailField>
          <DetailField label="账本哈希">
            <span className="font-mono text-[11px] break-all">
              {selectedDecided.entryHash || "（审计未入账）"}
            </span>
          </DetailField>
          {selectedDecided.auditRecorded === false && (
            <p className="text-[11px] leading-relaxed" style={{ color: "var(--warn)" }}>
              决策已生效，但服务端审计写入失败；此记录仅在当前页面会话可见。
            </p>
          )}
        </DetailSection>
      )}
      <Button
        size="sm"
        variant="secondary"
        className="w-full"
        onClick={() => {
          openModule("chat", { selectedId: selected.item.session_id, detailOpen: true });
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
      ) : approvals.isLoading && filter !== "approved" && filter !== "rejected" ? (
        <LoadingState title="加载待处理审批…" />
      ) : history.isLoading && (filter === "approved" || filter === "rejected") && decisions.length === 0 ? (
        <LoadingState title="加载审批历史…" />
      ) : approvals.isError && (filter === "pending" || filter === "expired") ? (
        toClientError(approvals.error).kind === "forbidden" ? <ForbiddenState /> :
        <ErrorState title="审批队列加载失败" hint={toClientError(approvals.error).message} action={<Button size="sm" onClick={() => approvals.refetch()}>重试</Button>} />
      ) : history.isError && (filter === "approved" || filter === "rejected") && shown.length === 0 ? (
        toClientError(history.error).kind === "forbidden" ? <ForbiddenState /> :
        <ErrorState title="审批历史加载失败" hint={toClientError(history.error).message} action={<Button size="sm" onClick={() => history.refetch()}>重试</Button>} />
      ) : shown.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title={EMPTY_COPY[filter].title}
          hint={EMPTY_COPY[filter].hint}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mx-auto flex max-w-2xl flex-col gap-3">
            {history.isError && (filter === "approved" || filter === "rejected") && (
              <div className="rounded-[var(--radius)] border px-3 py-2 text-[12px]" style={{ borderColor: "var(--warn)", color: "var(--warn)" }} role="status">
                服务端审批历史暂不可用；以下记录可能不完整，请恢复查询后核对。
                <Button size="xs" variant="ghost" className="ml-2" onClick={() => history.refetch()}>重试</Button>
              </div>
            )}
            {shown.map(({ item, status }) => (
              <ApprovalCard
                key={item.call_id}
                model={toModel(item, status)}
                onSelect={() => select("approvals", item.call_id)}
                onApprove={() => onDecide(item, true)}
                onReject={() => onDecide(item, false)}
                submitting={submittingIds.has(item.call_id)}
                error={decideErrors[item.call_id]}
              />
            ))}
          </div>
        </div>
      )}
    </ModuleLayout>
  );
}
