import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Activity, MessageSquare } from "lucide-react";
import { Button } from "@/components/Button";
import {
  ModuleLayout,
  ContextRail,
  RailGroupLabel,
  RailItem,
  ContentHeader,
  DetailToggleButton,
  DetailPanel,
  ResourceList,
  ResourceRow,
  StatusDot,
  StatusBadge,
  EmptyState,
  LoadingState,
  ErrorState,
  UnsupportedState,
} from "@/components/desktop";
import { ipc } from "@/ipc/client";
import { useUi } from "@/stores/ui";
import { useConnection } from "@/stores/connection";
import { formatRelative } from "@/lib/format";
import type { RunSummaryWire } from "@/contracts/stream";
import { RUN_STATUS_META } from "@/features/runs/projection";
import { useRunProjection } from "@/features/runs/useRuns";
import { RunDetailBody } from "@/features/runs/RunDetail";

type TimeRange = "all" | "today" | "week";

const STATUS_FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "running", label: "运行中" },
  { key: "completed", label: "已完成" },
  { key: "failed", label: "失败" },
  { key: "cancelled", label: "已取消" },
];

const TIME_FILTERS: { key: TimeRange; label: string }[] = [
  { key: "all", label: "全部时间" },
  { key: "today", label: "今天" },
  { key: "week", label: "近 7 天" },
];

export function RunsPage() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authenticated = useConnection((s) => s.auth.authenticated);
  const eventReplay = useConnection((s) => s.capabilities.eventReplay);
  const runSnapshot = useConnection((s) => s.capabilities.runSnapshot);
  const status = useUi((s) => s.modules.runs.filter) ?? "all";
  const setFilter = useUi((s) => s.setFilter);
  const selectedId = useUi((s) => s.modules.runs.selectedId);
  const select = useUi((s) => s.select);
  const navigate = useNavigate();
  const [timeRange, setTimeRange] = useState<TimeRange>("all");
  const connected = Boolean(connectionId && authenticated);

  const runs = useQuery<RunSummaryWire[]>({
    queryKey: ["runs", connectionId],
    enabled: connected && runSnapshot,
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "runs.list", limit: 60 },
      });
      return Array.isArray(result) ? (result as RunSummaryWire[]) : [];
    },
  });

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: runs.data?.length ?? 0 };
    for (const run of runs.data ?? []) map[run.status] = (map[run.status] ?? 0) + 1;
    return map;
  }, [runs.data]);

  const visible = (runs.data ?? [])
    .filter((run) => inRange(run, timeRange))
    .filter((run) => status === "all" || run.status === status);

  const {
    projection,
    isLoading: detailLoading,
    isError: detailError,
    error: detailErrorMessage,
    isLive,
    refetch: refetchDetail,
  } = useRunProjection(selectedId ?? undefined);

  const rail = (
    <ContextRail title="运行">
      <RailGroupLabel>状态</RailGroupLabel>
      {STATUS_FILTERS.map((f) => (
        <RailItem
          key={f.key}
          label={f.label}
          count={f.key === "all" ? counts.all : (counts[f.key] ?? 0)}
          selected={status === f.key}
          onClick={() => setFilter("runs", f.key)}
        />
      ))}
      <RailGroupLabel>时间范围</RailGroupLabel>
      {TIME_FILTERS.map((f) => (
        <RailItem key={f.key} label={f.label} selected={timeRange === f.key} onClick={() => setTimeRange(f.key)} />
      ))}
    </ContextRail>
  );

  const backToChat = () => {
    if (!selectedId) return;
    useUi.getState().select("chat", selectedId);
    navigate("/chat");
  };

  const detail =
    selectedId && projection ? (
      <DetailPanel
        title={<span className="flex items-center gap-2">运行详情 {isLive && <StatusDot tone="running" pulse size={7} />}</span>}
        onClose={() => useUi.getState().setDetailOpen("runs", false)}
      >
        {detailError && (
          <div
            className="mb-3 rounded-[var(--radius)] border px-2.5 py-2 text-[11px]"
            style={{ borderColor: "var(--danger)", background: "var(--danger-tint)", color: "var(--fg)" }}
          >
            运行订阅已中断：{detailErrorMessage ?? "请重新加载快照"}
          </div>
        )}
        <RunDetailBody projection={projection} eventReplay={eventReplay} />
        <Button size="sm" variant="secondary" className="mt-1 w-full" onClick={backToChat}>
          <MessageSquare size={14} />
          回到来源会话
        </Button>
      </DetailPanel>
    ) : selectedId && detailLoading ? (
      <DetailPanel title="运行详情" onClose={() => useUi.getState().setDetailOpen("runs", false)}>
        <LoadingState title="加载运行快照…" />
      </DetailPanel>
    ) : selectedId && detailError ? (
      <DetailPanel title="运行详情" onClose={() => useUi.getState().setDetailOpen("runs", false)}>
        <ErrorState
          title="运行详情加载失败"
          hint={detailErrorMessage}
          action={<Button size="xs" variant="secondary" onClick={() => void refetchDetail()}>重新加载</Button>}
        />
      </DetailPanel>
    ) : undefined;

  return (
    <ModuleLayout module="runs" rail={rail} detail={detail}>
      <ContentHeader
        title="运行"
        subtitle="Multi-Agent 运行 · 三层委派 · 独立 token 预算"
        actions={<DetailToggleButton module="runs" />}
      />
      {!connected ? (
        <EmptyState icon={Activity} title="连接后查看运行" hint="运行 = 会话的执行视图，来自后端的阶段快照。" />
      ) : !runSnapshot ? (
        <UnsupportedState title="当前服务器不支持运行快照" hint="服务器未声明 runSnapshot，桌面端不会伪装运行详情可用。" />
      ) : runs.isLoading ? (
        <LoadingState title="加载运行列表…" />
      ) : runs.isError ? (
        <ErrorState title="运行列表加载失败" hint="无法读取会话列表，请检查连接后重试。" />
      ) : visible.length === 0 ? (
        <EmptyState icon={Activity} title="没有匹配的运行" hint="调整状态或时间范围筛选。" />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <ResourceList>
            {visible.map((run) => {
              const meta = RUN_STATUS_META[run.status];
              return (
                <ResourceRow
                  key={run.id}
                  selected={selectedId === run.id}
                  onClick={() => select("runs", run.id)}
                  leading={<StatusDot tone={meta.tone} pulse={run.status === "running"} size={9} />}
                  title={run.title || "未命名运行"}
                  subtitle={`${run.steps} 阶段 · ${formatRelative(run.updated_at)}`}
                  meta={formatRelative(run.updated_at)}
                  trailing={
                    <StatusBadge tone={meta.tone} pulse={run.status === "running"}>
                      {meta.label}
                    </StatusBadge>
                  }
                />
              );
            })}
          </ResourceList>
        </div>
      )}
    </ModuleLayout>
  );
}

function inRange(run: Pick<RunSummaryWire, "updated_at">, range: TimeRange): boolean {
  if (range === "all") return true;
  const days = (Date.now() - new Date(run.updated_at).getTime()) / 86_400_000;
  return range === "today" ? days < 1 : days <= 7;
}
