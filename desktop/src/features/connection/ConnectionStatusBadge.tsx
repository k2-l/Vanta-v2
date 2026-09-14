import type { ConnectionStatus } from "@/contracts/connection";
import { useConnection } from "@/stores/connection";
import { cn } from "@/lib/cn";

const STATUS_META: Record<ConnectionStatus, { label: string; color: string }> = {
  unconfigured: { label: "未配置", color: "var(--unknown)" },
  testing: { label: "测试中", color: "var(--warn)" },
  unauthenticated: { label: "未登录", color: "var(--warn)" },
  authenticating: { label: "登录中", color: "var(--warn)" },
  online: { label: "在线", color: "var(--ok)" },
  degraded: { label: "降级", color: "var(--warn)" },
  offline: { label: "离线", color: "var(--danger)" },
  reconnecting: { label: "重连中", color: "var(--warn)" },
};

/** 全局连接状态徽标——侧栏底部常驻（方案 §9.2：状态必须是全局的）。 */
export function ConnectionStatusBadge({ collapsed }: { collapsed?: boolean }) {
  const status = useConnection((s) => s.status);
  const version = useConnection((s) => s.serverVersion);
  const meta = STATUS_META[status];

  return (
    <div
      className={cn("flex items-center gap-2 rounded-md px-3 h-9 text-xs", collapsed && "justify-center px-0")}
      style={{ background: "var(--bg-inset)", color: "var(--fg-muted)" }}
      title={`连接状态：${meta.label}${version ? ` · 后端 ${version}` : ""}`}
    >
      <span className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: meta.color }} />
      {!collapsed && (
        <span className="truncate">
          {meta.label}
          {version && <span style={{ color: "var(--fg-subtle)" }}> · {version}</span>}
        </span>
      )}
    </div>
  );
}
