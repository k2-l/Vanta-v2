/**
 * 状态表达（规范 §3.3）：颜色不是唯一信号，同时包含形状 / 文字 / 脉冲。
 * 领域状态先归一化为 Tone，再交给 StatusDot / StatusBadge 呈现。
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tone = "running" | "accent" | "ok" | "warn" | "danger" | "neutral";

const TONE_COLOR: Record<Tone, string> = {
  running: "var(--accent)",
  accent: "var(--accent)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  danger: "var(--danger)",
  neutral: "var(--unknown)",
};

const TONE_TINT: Record<Tone, string> = {
  running: "var(--accent-tint)",
  accent: "var(--accent-tint)",
  ok: "var(--ok-tint)",
  warn: "var(--warn-tint)",
  danger: "var(--danger-tint)",
  neutral: "color-mix(in srgb, var(--unknown) 16%, transparent)",
};

export function StatusDot({
  tone,
  pulse,
  size = 8,
  className,
}: {
  tone: Tone;
  /** 运行中脉冲；不传时 running 默认脉冲。 */
  pulse?: boolean;
  size?: number;
  className?: string;
}) {
  const animated = pulse ?? tone === "running";
  return (
    <span
      className={cn("inline-block shrink-0 rounded-full", animated && "vanta-pulse", className)}
      style={{ width: size, height: size, background: TONE_COLOR[tone] }}
    />
  );
}

export function StatusBadge({
  tone,
  children,
  icon,
  pulse,
  className,
}: {
  tone: Tone;
  children: ReactNode;
  icon?: ReactNode;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium leading-none",
        className,
      )}
      style={{ background: TONE_TINT[tone], color: TONE_COLOR[tone] }}
    >
      {icon ?? <StatusDot tone={tone} pulse={pulse} size={6} />}
      <span className="truncate">{children}</span>
    </span>
  );
}
