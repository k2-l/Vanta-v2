import { useMemo, useState } from "react";
import { Layers, Plus, Settings2 } from "lucide-react";
import {
  ModuleLayout,
  ContextRail,
  RailGroupLabel,
  RailItem,
  ContentHeader,
  StatusBadge,
  EmptyState,
  LoadingState,
  ErrorState,
  OfflineState,
} from "@/components/desktop";
import { Button } from "@/components/Button";
import { useUi } from "@/stores/ui";
import { useConnection } from "@/stores/connection";
import { formatRelative } from "@/lib/format";
import { useCapabilities } from "@/features/capabilities/useCapabilities";
import {
  AVAILABILITY,
  CAPABILITY_KIND,
  type CapabilityItem,
  type CapabilityKind,
} from "@/features/capabilities/model";
import type { ContainerWire } from "@/contracts/containers";
import type { AgentWire } from "@/contracts/agents";
import type { SkillWire } from "@/contracts/skills";
import type { McpServerWire } from "@/contracts/mcp";
import {
  CreateContainerDialog,
  ManageContainerDialog,
} from "@/features/containers/ContainerRuntimeDialogs";
import { AgentDialog } from "@/features/agents/AgentDialog";
import { SkillDialog } from "@/features/skills/SkillDialog";
import { useReindexSkills } from "@/features/skills/useSkillManagement";
import { McpServerDialog } from "@/features/mcp/McpServerDialog";

const KINDS = Object.keys(CAPABILITY_KIND) as CapabilityKind[];

export function CapabilitiesPage() {
  const kindFilter = (useUi((s) => s.modules.capabilities.filter) ?? "all") as "all" | CapabilityKind;
  const setFilter = useUi((s) => s.setFilter);
  const connected = useConnection((s) => Boolean(s.activeConnectionId && s.auth.authenticated));
  const offline = useConnection((s) => s.status === "offline");
  const [containerDialog, setContainerDialog] = useState<"create" | ContainerWire | null>(null);
  const [agentDialog, setAgentDialog] = useState<"create" | AgentWire | null>(null);
  const [skillDialog, setSkillDialog] = useState<"create" | SkillWire | null>(null);
  const [mcpDialog, setMcpDialog] = useState<"create" | McpServerWire | null>(null);
  const reindexSkills = useReindexSkills();

  const query = useCapabilities();
  const all = query.data?.items ?? [];
  const agents = query.data?.agents ?? [];
  const skills = query.data?.skills ?? [];
  const mcpServers = query.data?.mcpServers ?? [];
  const containers = query.data?.containers ?? [];
  const activeContainer = containerDialog && containerDialog !== "create"
    ? containers.find((item) => item.id === containerDialog.id) ?? containerDialog
    : null;
  const failed = query.data?.failed ?? [];
  const lastSync = query.dataUpdatedAt ? new Date(query.dataUpdatedAt).toISOString() : undefined;

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: all.length };
    for (const c of all) map[c.kind] = (map[c.kind] ?? 0) + 1;
    return map;
  }, [all]);

  const items = all.filter((c) => (kindFilter === "all" ? true : c.kind === kindFilter));

  const groups = useMemo(() => {
    const bySource = new Map<string, CapabilityItem[]>();
    for (const c of items) {
      const list = bySource.get(c.source) ?? [];
      list.push(c);
      bySource.set(c.source, list);
    }
    return Array.from(bySource.entries());
  }, [items]);

  const rail = (
    <ContextRail title="能力">
      <RailGroupLabel>分类</RailGroupLabel>
      <RailItem label="全部" count={counts.all} selected={kindFilter === "all"} onClick={() => setFilter("capabilities", "all")} />
      {KINDS.map((k) => {
        const Icon = CAPABILITY_KIND[k].icon;
        return (
          <RailItem
            key={k}
            label={CAPABILITY_KIND[k].label}
            icon={<Icon size={15} />}
            count={counts[k] ?? 0}
            selected={kindFilter === k}
            onClick={() => setFilter("capabilities", k)}
          />
        );
      })}
    </ContextRail>
  );

  const header = (
    <ContentHeader
      title="能力"
      subtitle="只呈现后端已声明或本机确实可用的能力，可用状态来自运行时事实（规范 §4.5）"
      actions={
        <>
          {connected && kindFilter === "runtime" && (
            <Button size="xs" onClick={() => setContainerDialog("create")}>
              <Plus size={13} />
              创建容器
            </Button>
          )}
          {connected && kindFilter === "agent" && (
            <Button size="xs" onClick={() => setAgentDialog("create")}>
              <Plus size={13} />
              创建 Agent
            </Button>
          )}
          {connected && kindFilter === "skill" && (
            <>
              <Button size="xs" variant="secondary" disabled={reindexSkills.isPending} onClick={() => reindexSkills.mutate()}>
                {reindexSkills.isPending ? "重建索引中…" : "重建索引"}
              </Button>
              <Button size="xs" onClick={() => setSkillDialog("create")}>
                <Plus size={13} />
                创建 Skill
              </Button>
            </>
          )}
          {connected && kindFilter === "mcp" && (
            <Button size="xs" onClick={() => setMcpDialog("create")}>
              <Plus size={13} />
              创建 MCP
            </Button>
          )}
          <span className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
            {connected && query.isSuccess ? `共 ${all.length} 项` : null}
          </span>
        </>
      }
    />
  );

  const body = () => {
    if (!connected) {
      return offline ? (
        <OfflineState />
      ) : (
        <EmptyState icon={Layers} title="未连接服务器" hint="在设置中激活连接并登录后，此处会列出后端已声明的能力。" />
      );
    }
    if (query.isLoading) return <LoadingState title="正在同步能力目录…" />;
    if (query.isError) {
      return (
        <ErrorState
          title="能力目录加载失败"
          hint="无法从后端读取 Agent、Skill、MCP、知识库或执行环境目录。"
          action={
            <Button variant="secondary" onClick={() => query.refetch()}>
              重试
            </Button>
          }
        />
      );
    }
    if (all.length === 0) {
      return <EmptyState icon={Layers} title="后端未声明任何能力" hint="当前连接的后端没有已注册的 Agent、Skill、MCP、知识库或执行环境。" />;
    }
    if (items.length === 0) {
      return <EmptyState icon={Layers} title="该分类下没有已声明的能力" hint="切换左侧分类查看其他来源。" />;
    }
    return (
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          {failed.length > 0 && (
            <div
              className="rounded-[var(--radius-lg)] border px-3 py-2 text-[12px]"
              style={{ background: "var(--warn-tint)", borderColor: "var(--warn)", color: "var(--warn)" }}
            >
              部分来源未能同步：{failed.map((k) => CAPABILITY_KIND[k].label).join("、")}。以下仅展示已成功读取的能力。
            </div>
          )}
          {groups.map(([source, list]) => (
            <section key={source}>
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-[12px] font-semibold" style={{ color: "var(--fg-muted)" }}>
                  {source}
                </h2>
                <span className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
                  {list.length} 项
                </span>
              </div>
              <div className="flex flex-col gap-2">
                {list.map((cap) => (
                  <CapabilityRow
                    key={cap.id}
                    cap={cap}
                    lastSync={lastSync}
                    onManage={
                      cap.kind === "agent"
                        ? () => {
                            const agent = agents.find((item) => `agent:${item.id}` === cap.id);
                            if (agent) setAgentDialog(agent);
                          }
                        : cap.kind === "skill"
                        ? () => {
                            const skill = skills.find((item) => `skill:${item.id}` === cap.id);
                            if (skill) setSkillDialog(skill);
                          }
                        : cap.kind === "mcp"
                        ? () => {
                            const server = mcpServers.find((item) => `mcp:${item.name}` === cap.id);
                            if (server) setMcpDialog(server);
                          }
                        : cap.kind === "runtime"
                        ? () => {
                            const container = containers.find((item) => `runtime:${item.id}` === cap.id);
                            if (container) setContainerDialog(container);
                          }
                        : undefined
                    }
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    );
  };

  return (
    <>
      <ModuleLayout module="capabilities" rail={rail}>
        {header}
        {body()}
      </ModuleLayout>
      {containerDialog === "create" && (
        <CreateContainerDialog
          onClose={() => setContainerDialog(null)}
          onCreated={(container) => setContainerDialog(container)}
        />
      )}
      {activeContainer && (
        <ManageContainerDialog container={activeContainer} onClose={() => setContainerDialog(null)} />
      )}
      {agentDialog === "create" && <AgentDialog onClose={() => setAgentDialog(null)} />}
      {agentDialog && agentDialog !== "create" && (
        <AgentDialog agent={agentDialog} onClose={() => setAgentDialog(null)} />
      )}
      {skillDialog === "create" && <SkillDialog onClose={() => setSkillDialog(null)} />}
      {skillDialog && skillDialog !== "create" && (
        <SkillDialog skill={skillDialog} onClose={() => setSkillDialog(null)} />
      )}
      {mcpDialog === "create" && <McpServerDialog onClose={() => setMcpDialog(null)} />}
      {mcpDialog && mcpDialog !== "create" && (
        <McpServerDialog server={mcpDialog} onClose={() => setMcpDialog(null)} />
      )}
    </>
  );
}

function CapabilityRow({ cap, lastSync, onManage }: { cap: CapabilityItem; lastSync?: string; onManage?: () => void }) {
  const Icon = CAPABILITY_KIND[cap.kind].icon;
  const avail = AVAILABILITY[cap.availability];
  return (
    <div
      className="flex items-start gap-3 rounded-[var(--radius-lg)] border p-3"
      style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
    >
      <span
        className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[var(--radius)]"
        style={{ background: "var(--surface-inset)", color: "var(--fg-muted)" }}
      >
        <Icon size={16} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-[13px] font-medium" style={{ color: "var(--fg)" }}>
            {cap.name}
          </p>
          <span className="flex shrink-0 items-center gap-2">
            <StatusBadge tone={avail.tone}>{avail.label}</StatusBadge>
            {onManage && (
              <Button size="xs" variant="secondary" onClick={onManage}>
                <Settings2 size={12} />管理
              </Button>
            )}
          </span>
        </div>
        <p className="mt-0.5 text-[12px]" style={{ color: "var(--fg-muted)" }}>
          {cap.detail}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]" style={{ color: "var(--fg-subtle)" }}>
          <span>{CAPABILITY_KIND[cap.kind].label}</span>
          {cap.location && <span>运行于 {cap.location}</span>}
          {cap.dependency && <span className="font-mono">依赖 {cap.dependency}</span>}
          {lastSync && <span>{formatRelative(lastSync)}同步</span>}
        </div>
      </div>
    </div>
  );
}
