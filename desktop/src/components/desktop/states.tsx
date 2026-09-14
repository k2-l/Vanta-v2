/**
 * 页面状态组件（规范 §3.3 / §7）：空 / 加载 / 错误 / 离线 / 无权限 / 能力不支持
 * 都必须有独立、可走查的呈现，而不是空白或伪装可用。
 */

import type { ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  Inbox,
  Loader2,
  Lock,
  WifiOff,
  type LucideIcon,
} from "lucide-react";

type Tone = "neutral" | "warn" | "danger";

const TONE: Record<Tone, { fg: string; bg: string }> = {
  neutral: { fg: "var(--fg-subtle)", bg: "var(--surface-inset)" },
  warn: { fg: "var(--warn)", bg: "var(--warn-tint)" },
  danger: { fg: "var(--danger)", bg: "var(--danger-tint)" },
};

function StateShell({
  icon: Icon,
  tone = "neutral",
  title,
  hint,
  action,
  spin,
}: {
  icon: LucideIcon;
  tone?: Tone;
  title: string;
  hint?: string;
  action?: ReactNode;
  spin?: boolean;
}) {
  const t = TONE[tone];
  return (
    <div className="grid h-full place-items-center p-8">
      <div className="flex max-w-sm flex-col items-center gap-3 text-center">
        <span
          className="grid h-11 w-11 place-items-center rounded-[var(--radius-md)]"
          style={{ background: t.bg, color: t.fg }}
        >
          <Icon size={20} className={spin ? "animate-spin" : undefined} />
        </span>
        <p className="text-[13px] font-medium" style={{ color: "var(--fg)" }}>
          {title}
        </p>
        {hint && (
          <p className="text-[12px] leading-relaxed" style={{ color: "var(--fg-muted)" }}>
            {hint}
          </p>
        )}
        {action && <div className="mt-1">{action}</div>}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon = Inbox,
  action,
  children,
}: {
  title: string;
  hint?: string;
  icon?: LucideIcon;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return <StateShell icon={icon} title={title} hint={hint} action={action ?? children} />;
}

export function LoadingState({ title = "加载中…", hint }: { title?: string; hint?: string }) {
  return <StateShell icon={Loader2} title={title} hint={hint} spin />;
}

export function ErrorState({
  title = "出错了",
  hint,
  action,
}: {
  title?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return <StateShell icon={AlertTriangle} tone="danger" title={title} hint={hint} action={action} />;
}

export function OfflineState({
  title = "已离线",
  hint = "无法连接到当前服务器。凭据由本机 Rust Core 保管，恢复网络后可重连。",
  action,
}: {
  title?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return <StateShell icon={WifiOff} tone="warn" title={title} hint={hint} action={action} />;
}

export function ForbiddenState({
  title = "无权限",
  hint = "当前账号没有执行此操作的权限。",
  action,
}: {
  title?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return <StateShell icon={Lock} tone="warn" title={title} hint={hint} action={action} />;
}

export function UnsupportedState({
  title = "服务器未声明此能力",
  hint = "桌面端只呈现后端已声明的能力，不会伪装可用（规范 §4.5）。",
  action,
}: {
  title?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return <StateShell icon={Ban} tone="neutral" title={title} hint={hint} action={action} />;
}
