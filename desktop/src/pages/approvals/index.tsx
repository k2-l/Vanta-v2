import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";

export function ApprovalsPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="审批" description="全局审批队列——不属于某个临时打开的聊天页面" />
      <div className="flex-1">
        <EmptyState title="G3：审批与产物" hint="全局 Approval Center、pending 查询与连接后重放将在 G3 阶段接入。" />
      </div>
    </div>
  );
}
