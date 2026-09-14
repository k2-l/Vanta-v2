/**
 * 对话步骤卡（Plan G2 / 规范 §4.1）——把运行投影的 phase 与工具事件内联展示为步骤状态。
 * 默认折叠为「N 步」摘要，可展开查看每一步与工具结果。
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { StatusDot } from "@/components/desktop/status";
import { deriveTimeline, phaseCount, toolCount, type RunProjection } from "@/features/runs/projection";

export function StepList({ projection, defaultOpen = false }: { projection: RunProjection; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const items = deriveTimeline(projection);
  if (items.length === 0) return null;

  const running = projection.status === "running";
  const steps = phaseCount(projection);
  const tools = toolCount(projection);

  return (
    <div
      className="mr-auto max-w-full overflow-hidden rounded-[var(--radius)] border"
      style={{ borderColor: "var(--border)", background: "var(--surface-nav)" }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-[var(--surface-inset)]"
      >
        {open ? (
          <ChevronDown size={14} style={{ color: "var(--fg-subtle)" }} />
        ) : (
          <ChevronRight size={14} style={{ color: "var(--fg-subtle)" }} />
        )}
        <StatusDot tone={running ? "running" : "ok"} pulse={running} size={7} />
        <span className="text-[12px] font-medium" style={{ color: "var(--fg)" }}>
          {running ? "执行中" : "已完成"}
        </span>
        <span className="text-[11px]" style={{ color: "var(--fg-subtle)" }}>
          · {steps} 阶段 · {tools} 工具
        </span>
      </button>
      {open && (
        <ol className="flex flex-col gap-0.5 border-t px-3 py-2" style={{ borderColor: "var(--border)" }}>
          {items.map((item) => (
            <li key={item.id} className="flex items-center gap-2">
              {item.id.startsWith("t_") ? (
                <Wrench size={11} style={{ color: "var(--fg-subtle)" }} className="shrink-0" />
              ) : (
                <StatusDot tone={item.tone} pulse={item.tone === "running"} size={7} />
              )}
              <span className="min-w-0 flex-1 truncate text-[12px]" style={{ color: "var(--fg-muted)" }}>
                {item.label}
              </span>
              {item.detail && (
                <span className="shrink-0 truncate text-[10px]" style={{ color: "var(--fg-subtle)", maxWidth: 140 }}>
                  {item.detail}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
