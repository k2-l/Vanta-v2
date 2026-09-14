/**
 * 运行时间线（规范 §4.1 / §4.2）——执行轨迹的纵向事件流。
 * 断线重连后按 sequence 恢复（G2 接入）；此处只负责呈现已归一化事件。
 */

import { StatusDot, type Tone } from "./status";
import { formatTime } from "@/lib/format";

export type RunTimelineItem = {
  id: string;
  label: string;
  detail?: string;
  at: string;
  tone: Tone;
};

export function RunTimeline({ items }: { items: RunTimelineItem[] }) {
  if (items.length === 0) {
    return (
      <p className="px-1 text-[12px]" style={{ color: "var(--fg-subtle)" }}>
        暂无事件
      </p>
    );
  }
  return (
    <ol className="relative flex flex-col">
      {items.map((item, index) => {
        const last = index === items.length - 1;
        return (
          <li key={item.id} className="relative flex gap-3 pb-3.5 last:pb-0">
            {!last && (
              <span
                aria-hidden
                className="absolute left-[5px] top-3.5 bottom-0 w-px"
                style={{ background: "var(--border)" }}
              />
            )}
            <span className="relative z-10 mt-1 shrink-0">
              <StatusDot tone={item.tone} size={11} pulse={item.tone === "running"} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-[12px] font-medium" style={{ color: "var(--fg)" }}>
                  {item.label}
                </p>
                <time className="shrink-0 text-[10px] tabular-nums" style={{ color: "var(--fg-subtle)" }}>
                  {formatTime(item.at)}
                </time>
              </div>
              {item.detail && (
                <p className="mt-0.5 truncate text-[11px]" style={{ color: "var(--fg-muted)" }}>
                  {item.detail}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
