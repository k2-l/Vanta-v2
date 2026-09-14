/**
 * 全局连接状态徽标（规范 §9.2）——标题栏常驻，展示活动连接与状态。
 * 状态是全局的，任何位置读取同一份连接 store。
 */

import { useConnections } from "./useConnections";
import { CONNECTION_STATUS_META } from "./status";
import { useConnection } from "@/stores/connection";
import { StatusDot } from "@/components/desktop/status";

export function ConnectionStatusBadge() {
  const status = useConnection((s) => s.status);
  const version = useConnection((s) => s.serverVersion);
  const activeId = useConnection((s) => s.activeConnectionId);
  const { data: connections } = useConnections();
  const meta = CONNECTION_STATUS_META[status];
  const label = connections?.find((c) => c.id === activeId)?.label;

  return (
    <div
      className="no-drag flex h-7 items-center gap-2 rounded-full px-2.5"
      style={{ background: "var(--surface-inset)", border: "1px solid var(--border)" }}
      title={`连接状态：${meta.label}${version ? ` · 后端 ${version}` : ""}`}
    >
      <StatusDot tone={meta.tone} />
      <span className="max-w-[180px] truncate text-[12px]" style={{ color: "var(--fg)" }}>
        {label ?? "未连接"}
      </span>
      <span className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
        · {meta.label}
      </span>
    </div>
  );
}
