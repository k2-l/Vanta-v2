/**
 * 运行详情呈现（Plan G2）——对话页与运行页共用同一投影 view model。
 * Agent 树来自 phase 图；用量为独立 token；时间线合并 phase 与工具事件。
 */

import { Package, Wrench } from "lucide-react";
import { Button } from "@/components/Button";
import { DetailSection, DetailField } from "@/components/desktop/DetailPanel";
import { RunTimeline } from "@/components/desktop/RunTimeline";
import { StatusBadge, StatusDot, type Tone } from "@/components/desktop/status";
import { formatDuration, formatTokens } from "@/lib/format";
import { useArtifacts } from "@/features/artifacts/useArtifacts";
import { useModuleNavigation } from "@/app/moduleNavigation";
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
  type ToolEvent,
  type ToolStatus,
} from "./projection";

const TOOL_TONE: Record<ToolStatus, Tone> = { running: "running", ok: "ok", failed: "danger" };
const TOOL_LABEL: Record<ToolStatus, string> = { running: "调用中", ok: "成功", failed: "失败" };

/** Bash 取 command，其余工具序列化 args；供运行详情如实展示"调用详细"。 */
function formatToolInput(inputs?: Record<string, unknown>): string {
  if (!inputs || Object.keys(inputs).length === 0) return "";
  if (typeof inputs.command === "string") return inputs.command;
  try {
    return JSON.stringify(inputs, null, 2);
  } catch {
    return String(inputs);
  }
}

/** 单次工具调用卡：工具名 + 状态 + 入参(命令) + 输出/错误。 */
function ToolCallCard({ tool }: { tool: ToolEvent }) {
  const input = formatToolInput(tool.inputs);
  const body = tool.status === "failed" ? tool.error || tool.output : tool.output;
  const clipped = body && body.length > 800 ? `${body.slice(0, 800)}…（已截断）` : body;
  return (
    <div
      className="rounded-[var(--radius)] border px-2.5 py-2"
      style={{ borderColor: "var(--border)", background: "var(--surface-inset)" }}
    >
      <div className="mb-1 flex items-center gap-1.5">
        <Wrench size={11} style={{ color: "var(--fg-subtle)" }} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate font-mono text-[11px]" style={{ color: "var(--fg)" }}>
          {tool.tool}
        </span>
        <StatusBadge tone={TOOL_TONE[tool.status]}>{TOOL_LABEL[tool.status]}</StatusBadge>
      </div>
      {input && (
        <pre
          className="mb-1 max-h-24 overflow-auto whitespace-pre-wrap break-all rounded px-2 py-1 font-mono text-[10.5px] leading-relaxed"
          style={{ background: "var(--surface-overlay)", color: "var(--fg-muted)" }}
        >
          {input}
        </pre>
      )}
      {clipped && (
        <pre
          className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded px-2 py-1 font-mono text-[10.5px] leading-relaxed"
          style={{
            background: "var(--surface-overlay)",
            color: tool.status === "failed" ? "var(--danger)" : "var(--fg-subtle)",
          }}
        >
          {clipped}
        </pre>
      )}
    </div>
  );
}

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
  runHistory,
}: {
  projection: RunProjection;
  /** 后端是否支持事件按序重放（否则显示降级提示）。 */
  eventReplay: boolean;
  /** 后端是否持久化结构化运行遥测。 */
  runHistory: boolean;
}) {
  const openModule = useModuleNavigation();
  const artifacts = useArtifacts(undefined, projection.sessionId, true);
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
        {projection.durationMs != null && (
          <DetailField label="耗时">{formatDuration(projection.durationMs)}</DetailField>
        )}
      </DetailSection>

      <DetailSection title="Agent 树">
        <AgentTree projection={projection} />
      </DetailSection>

      <DetailSection title="用量（独立 token）">
        {projection.usage ? (
          <UsageMeter usage={projection.usage} />
        ) : !runHistory ? (
          <p className="text-[12px]" style={{ color: "var(--fg-subtle)" }}>当前服务器未提供运行遥测历史。</p>
        ) : (
          <p className="text-[12px]" style={{ color: "var(--fg-subtle)" }}>暂无持久用量；升级前创建的旧运行可能未记录。</p>
        )}
      </DetailSection>

      {projection.tools.length > 0 && (
        <DetailSection title={`工具调用（${toolCount(projection)}）`}>
          <div className="flex flex-col gap-2">
            {projection.tools.map((tool) => (
              <ToolCallCard key={tool.key} tool={tool} />
            ))}
          </div>
        </DetailSection>
      )}

      <DetailSection title="事件时间线">
        <RunTimeline items={timeline.map((t) => ({ id: t.id, label: t.label, detail: t.detail, at: "", tone: t.tone }))} />
      </DetailSection>

      <DetailSection title={`关联产物${artifacts.data?.length ? `（${artifacts.data.length}）` : ""}`}>
        {artifacts.isLoading ? (
          <p className="text-[12px]" style={{ color: "var(--fg-subtle)" }}>加载关联产物…</p>
        ) : artifacts.isError ? (
          <p className="text-[12px]" style={{ color: "var(--warn)" }}>关联产物暂不可用</p>
        ) : artifacts.data?.length ? (
          <div className="flex flex-col gap-1.5">
            {artifacts.data.slice(0, 5).map((artifact) => (
              <Button
                key={artifact.id}
                size="xs"
                variant="ghost"
                className="w-full justify-start"
                onClick={() => openModule("artifacts", { selectedId: artifact.id })}
              >
                <Package size={13} />
                <span className="truncate">{artifact.title}</span>
              </Button>
            ))}
          </div>
        ) : (
          <p className="text-[12px]" style={{ color: "var(--fg-subtle)" }}>本运行尚无关联产物。</p>
        )}
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
