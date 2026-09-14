import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";

export function RunsPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="运行" description="Multi-Agent 运行中心：三层委派树、独立 token、工具与 Critic" />
      <div className="flex-1">
        <EmptyState title="G2：Multi-Agent 运行中心" hint="Run 列表/详情、三层 Agent 树、snapshot/replay 将在 G2 阶段接入。" />
      </div>
    </div>
  );
}
