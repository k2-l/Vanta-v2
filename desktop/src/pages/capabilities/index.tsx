import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";

export function CapabilitiesPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="能力" description="Agent / Skill / Knowledge / Memory / Container / MCP" />
      <div className="flex-1">
        <EmptyState title="G4：能力管理与发布" hint="schema 驱动编辑器与依赖检查将在 G4 阶段接入。" />
      </div>
    </div>
  );
}
