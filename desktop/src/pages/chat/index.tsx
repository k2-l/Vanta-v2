import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";

export function ChatPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader title="对话" description="发起并查看任务的入口之一（Run 才是一等资源）" />
      <div className="flex-1">
        <EmptyState title="G1：可用聊天" hint="会话列表、消息历史、流式 Markdown、压缩 preview/commit 将在 G1 阶段接入。" />
      </div>
    </div>
  );
}
