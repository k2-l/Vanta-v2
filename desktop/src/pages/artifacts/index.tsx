import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";

export function ArtifactsPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="产物" description="Artifact 列表、来源追踪与安全导出" />
      <div className="flex-1">
        <EmptyState title="G3：审批与产物" hint="Artifact 列表/详情/导出、与运行的互相跳转将在 G3 阶段接入。" />
      </div>
    </div>
  );
}
