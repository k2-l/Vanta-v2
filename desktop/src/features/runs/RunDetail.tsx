/**
 * 运行详情呈现（Plan G2）——对话页与运行页共用同一投影 view model。
 * Agent 树来自 phase 图；用量为独立 token；时间线合并 phase 与工具事件。
 */

import { DetailSection, DetailField } from "@/components/desktop/DetailPanel";
import { RunTimeline } from "@/components/desktop/RunTimeline";
import { StatusBadge, StatusDot } from "@/components/desktop/status";
import { formatTokens } from "@/lib/format";
import {
  PHASE_TONE,
  RUN_STATUS_META,
  deriveTimeline,
  phaseCount,
  rootPhases,
  toolCount,
  type PhaseNode,
  type RunProjection,
  type RunUsage,
} from "./projection";

export function AgentTree({ projection, node, depth = 0 }: { projection: RunProjection; node?: PhaseNode; depth?: number }) {
  if (!node) {
    const roots = rootPhases(projection);
    if (roots.length === 0) {
      return <p className="text-[12px]" style={{ color: "var(--fg-subtle)" }}>暂无阶段</p>;
    }
    return (
      <div>
        {roots.map((r) => (
          <AgentTree key={r.id} projection={projection} node={r} depth={0} />
        ))}
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center gap-2 py-1" style={{ paddingLeft: depth * 14 }}>
        <StatusDot tone={PHASE_TONE[node.status]} pulse={node.status === "running"} size={8} />
        <span className="min-w-0 flex-1 truncate text-[12px]" style={{ color: "var(--fg)" }}>
          {node.label}
        </span>
        {node.detail && (
          <span className="shrink-0 truncate text-[10px]" style={{ color: "var(--fg-subtle)", maxWidth: 90 }}>
            {node.detail}
          </span>
        )}
      </div>
      {node.children.map((childId) =>
        projection.phases[childId] ? (
          <AgentTree key={childId} projection={projection} node={projection.phases[childId]} depth={depth + 1} />
        ) : null,
      )}
    </div>
  );
}

export function UsageMeter({ usage }: { usage: RunUsage }) {
  return (
    <div className="flex flex-col gap-1 text-[12px]">
      <div className="flex items-center justify-between">
        <span style={{ color: "var(--fg-muted)" }}>本轮</span>
        <span className="tabular-nums" style={{ color: "var(--fg)" }}>
          ↑{formatTokens(usage.turnInput)} · ↓{formatTokens(usage.turnOutput)}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span style={{ color: "var(--fg-muted)" }}>会话累计</span>
        <span className="tabular-nums" style={{ color: "var(--fg)" }}>
          ↑{formatTokens(usage.sessionInput)} · ↓{formatTokens(usage.sessionOutput)}
        </span>
      </div>
      {usage.model && (
        <div className="flex items-center justify-between">
          <span style={{ color: "var(--fg-muted)" }}>模型</span>
          <span className="truncate font-mono text-[11px]" style={{ color: "var(--fg-subtle)" }}>{usage.model}</span>
        </div>
      )}
    </div>
  );
}

export function RunDetailBody({
  projection,
  eventReplay,
}: {
  projection: RunProjection;
  /** 后端是否支持事件按序重放（否则显示降级提示）。 */
  eventReplay: boolean;
}) {
  const meta = RUN_STATUS_META[projection.status];
  const timeline = deriveTimeline(projection);
  return (
    <>
      <DetailSection title="概览">
        <div className="mb-2">
          <StatusBadge tone={meta.tone} pulse={projection.status === "running"}>
            {meta.label}
          </StatusBadge>
        </div>
        {projection.sessionId && (
          <DetailField label="Run ID">
            <span className="font-mono text-[11px]">{projection.sessionId}</span>
          </DetailField>
        )}
        <DetailField label="阶段 / 工具">
          {phaseCount(projection)} / {toolCount(projection)}
        </DetailField>
      </DetailSection>

      <DetailSection title="Agent 树">
        <AgentTree projection={projection} />
      </DetailSection>

      <DetailSection title="用量（独立 token）">
        {projection.usage ? (
          <UsageMeter usage={projection.usage} />
        ) : (
          <p className="text-[12px]" style={{ color: "var(--fg-subtle)" }}>历史运行不保留用量；实时运行时在此显示。</p>
        )}
      </DetailSection>

      <DetailSection title="事件时间线">
        <RunTimeline items={timeline.map((t) => ({ id: t.id, label: t.label, detail: t.detail, at: "", tone: t.tone }))} />
      </DetailSection>

      {!eventReplay && (
        <p
          className="rounded-[var(--radius)] border px-2.5 py-2 text-[11px] leading-relaxed"
          style={{ borderColor: "var(--border)", background: "var(--surface-inset)", color: "var(--fg-subtle)" }}
        >
          本服务器不支持事件按序重放；断线重连后将重新拉取阶段快照对账，而非逐条回放。
        </p>
      )}
    </>
  );
}
