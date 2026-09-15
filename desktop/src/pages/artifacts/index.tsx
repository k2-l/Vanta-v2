import { useMemo } from "react";
import { AlertTriangle, FileText, FileWarning, Package } from "lucide-react";
import { Button } from "@/components/Button";
import {
  ModuleLayout,
  ContextRail,
  RailGroupLabel,
  RailItem,
  ContentHeader,
  ResourceList,
  ResourceRow,
  ArtifactPreview,
  StatusBadge,
  EmptyState,
  LoadingState,
  OfflineState,
  ErrorState,
  ForbiddenState,
  type ArtifactPreviewModel,
} from "@/components/desktop";
import { useUi } from "@/stores/ui";
import { useConnection } from "@/stores/connection";
import { formatBytes, formatRelative } from "@/lib/format";
import type { ArtifactWire } from "@/contracts/resources";
import { toClientError } from "@/contracts/errors";
import {
  isSecret,
  kindLabel,
  previewKindFor,
  sensitivityMeta,
  severityMeta,
  useArtifacts,
} from "@/features/artifacts/useArtifacts";

function bytesOf(content?: string): number {
  return content ? new TextEncoder().encode(content).length : 0;
}

export function ArtifactsPage() {
  const connected = useConnection((s) => Boolean(s.activeConnectionId && s.auth.authenticated));
  const offline = useConnection((s) => s.status === "offline");
  const exportSupported = useConnection((s) => s.capabilities.artifactExport);
  const kindFilter = useUi((s) => s.modules.artifacts.filter) ?? "all";
  const setFilter = useUi((s) => s.setFilter);
  const selectedId = useUi((s) => s.modules.artifacts.selectedId);
  const select = useUi((s) => s.select);

  const artifacts = useArtifacts();
  const all = artifacts.data ?? [];

  const kinds = useMemo(() => Array.from(new Set(all.map((a) => a.kind))), [all]);
  const counts = useMemo(() => {
    const map: Record<string, number> = { all: all.length };
    for (const a of all) map[a.kind] = (map[a.kind] ?? 0) + 1;
    return map;
  }, [all]);

  const items = kindFilter === "all" ? all : all.filter((a) => a.kind === kindFilter);
  const selected = (selectedId ? all.find((a) => a.id === selectedId) : undefined) ?? items[0];

  const toModel = (a: ArtifactWire): ArtifactPreviewModel => ({
    id: a.id,
    name: a.title,
    typeLabel: kindLabel(a.kind),
    sizeLabel: isSecret(a) ? "—" : formatBytes(bytesOf(a.content)),
    sourceSession: a.producer || a.engagement_id || "未知来源",
    updatedAtLabel: a.created_at ? formatRelative(a.created_at) : "",
    previewKind: previewKindFor(a),
    preview: a.content,
    highRisk: isSecret(a),
    exportSupported,
  });

  const rail = (
    <ContextRail title="产物">
      <RailGroupLabel>类型</RailGroupLabel>
      <RailItem label="全部" count={counts.all} selected={kindFilter === "all"} onClick={() => setFilter("artifacts", "all")} />
      {kinds.map((k) => (
        <RailItem
          key={k}
          label={kindLabel(k)}
          count={counts[k] ?? 0}
          selected={kindFilter === k}
          onClick={() => setFilter("artifacts", k)}
        />
      ))}
    </ContextRail>
  );

  return (
    <ModuleLayout module="artifacts" rail={rail}>
      <ContentHeader title="产物" subtitle="看板 artifact · 来源追踪 · 受控预览（secret 仅元数据）" />
      {!connected ? (
        offline ? <OfflineState /> : <EmptyState icon={Package} title="连接后查看产物" hint="产物由 agent 的 board 工具产出。" />
      ) : artifacts.isLoading ? (
        <LoadingState title="加载产物…" />
      ) : artifacts.isError ? (
        toClientError(artifacts.error).kind === "forbidden" ? <ForbiddenState title="无权限查看产物" /> :
        <ErrorState title="产物加载失败" hint={toClientError(artifacts.error).message} action={<Button size="sm" onClick={() => artifacts.refetch()}>重试</Button>} />
      ) : items.length === 0 ? (
        <EmptyState icon={Package} title="没有该类型的产物" hint="切换左侧类型筛选，或等待 agent 产出。" />
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="flex h-full w-[300px] shrink-0 flex-col overflow-y-auto border-r p-2" style={{ borderColor: "var(--border)" }}>
            <ResourceList>
              {items.map((a) => {
                const sev = a.kind === "finding" ? severityMeta(a.severity) : undefined;
                const sens = sensitivityMeta(a.sensitivity);
                const Icon = isSecret(a) ? FileWarning : a.kind === "finding" ? AlertTriangle : FileText;
                return (
                  <ResourceRow
                    key={a.id}
                    dense
                    selected={selected?.id === a.id}
                    onClick={() => select("artifacts", a.id)}
                    leading={<Icon size={16} style={{ color: isSecret(a) ? "var(--danger)" : "var(--fg-subtle)" }} />}
                    title={a.title}
                    subtitle={`${kindLabel(a.kind)} · ${a.producer || "未知"} · ${a.created_at ? formatRelative(a.created_at) : ""}`}
                    trailing={
                      <span className="flex shrink-0 items-center gap-1">
                        {sev && <StatusBadge tone={sev.tone}>{sev.label}</StatusBadge>}
                        {a.sensitivity === "secret" && <StatusBadge tone={sens.tone}>{sens.label}</StatusBadge>}
                      </span>
                    }
                  />
                );
              })}
            </ResourceList>
          </div>
          <div className="min-w-0 flex-1">
            {selected ? (
              <ArtifactPreview
                model={toModel(selected)}
                onExport={() => {
                  /* 导出走 Rust Core 安全路径选择（artifact_export，capability 门控） */
                }}
              />
            ) : (
              <EmptyState title="选择一个产物预览" />
            )}
          </div>
        </div>
      )}
    </ModuleLayout>
  );
}
