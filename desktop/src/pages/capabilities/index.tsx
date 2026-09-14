import { useMemo } from "react";
import { Layers } from "lucide-react";
import {
  ModuleLayout,
  ContextRail,
  RailGroupLabel,
  RailItem,
  ContentHeader,
  StatusBadge,
  EmptyState,
} from "@/components/desktop";
import { useUi } from "@/stores/ui";
import { formatRelative } from "@/lib/format";
import {
  AVAILABILITY,
  CAPABILITY_ITEMS,
  CAPABILITY_KIND,
  type CapabilityItem,
  type CapabilityKind,
} from "@/features/capabilities/fixtures";

const KINDS = Object.keys(CAPABILITY_KIND) as CapabilityKind[];

export function CapabilitiesPage() {
  const kindFilter = useUi((s) => s.modules.capabilities.filter) ?? "all";
  const setFilter = useUi((s) => s.setFilter);

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: CAPABILITY_ITEMS.length };
    for (const c of CAPABILITY_ITEMS) map[c.kind] = (map[c.kind] ?? 0) + 1;
    return map;
  }, []);

  const items = CAPABILITY_ITEMS.filter((c) => (kindFilter === "all" ? true : c.kind === kindFilter));

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

  return (
    <ModuleLayout module="capabilities" rail={rail}>
      <ContentHeader
        title="能力"
        subtitle="只呈现后端已声明或本机确实可用的能力，不伪装可用（规范 §4.5）"
        actions={
          <span className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
            共 {items.length} 项
          </span>
        }
      />
      {items.length === 0 ? (
        <EmptyState icon={Layers} title="该分类下没有已声明的能力" hint="切换左侧分类查看其他来源。" />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
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
                    <CapabilityRow key={cap.id} cap={cap} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}
    </ModuleLayout>
  );
}

function CapabilityRow({ cap }: { cap: CapabilityItem }) {
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
          <StatusBadge tone={avail.tone}>{avail.label}</StatusBadge>
        </div>
        <p className="mt-0.5 text-[12px]" style={{ color: "var(--fg-muted)" }}>
          {cap.detail}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]" style={{ color: "var(--fg-subtle)" }}>
          <span>{CAPABILITY_KIND[cap.kind].label}</span>
          {cap.location && <span>运行于 {cap.location}</span>}
          {cap.dependency && <span className="font-mono">依赖 {cap.dependency}</span>}
          {cap.lastSync && <span>{formatRelative(cap.lastSync)}同步</span>}
        </div>
      </div>
    </div>
  );
}
