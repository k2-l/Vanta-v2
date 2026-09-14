import { PageHeader } from "@/components/PageHeader";
import { ConnectionManager } from "@/features/connection/ConnectionManager";
import { isTauri } from "@/ipc/client";

export function SettingsPage() {
  return (
    <div className="flex flex-col h-full">
      <PageHeader
        title="设置"
        description={isTauri() ? "连接、凭据、诊断与更新" : "浏览器 mock 模式（无 Tauri host）——连接/凭据为内存假数据"}
      />
      <div className="flex-1 overflow-auto p-6">
        <ConnectionManager />
      </div>
    </div>
  );
}
