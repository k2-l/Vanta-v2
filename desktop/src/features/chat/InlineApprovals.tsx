import { useMemo, useRef, useState } from "react";
import { Loader2, ShieldAlert } from "lucide-react";
import { Button } from "@/components/Button";
import { StatusBadge } from "@/components/desktop";
import type { ApprovalWire } from "@/contracts/resources";
import { toClientError } from "@/contracts/errors";
import {
  isApprovalExpired,
  riskMeta,
  useApprovals,
  useDecideApproval,
} from "@/features/approvals/useApprovals";

/** 当前会话的就地审批；全局队列和历史追溯仍由审批模块承载。 */
export function InlineApprovals({ sessionId, streaming }: { sessionId?: string; streaming: boolean }) {
  const approvals = useApprovals(streaming ? 1000 : 4000);
  const decide = useDecideApproval();
  const inFlight = useRef(new Set<string>());
  const [submitting, setSubmitting] = useState<Set<string>>(() => new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});

  const pending = useMemo(
    () =>
      (approvals.data ?? []).filter(
        (item) => item.session_id === sessionId && !isApprovalExpired(item),
      ),
    [approvals.data, sessionId],
  );

  if (!sessionId || pending.length === 0) return null;

  const submit = async (item: ApprovalWire, approved: boolean) => {
    if (inFlight.current.has(item.call_id) || isApprovalExpired(item)) return;
    inFlight.current.add(item.call_id);
    setSubmitting((current) => new Set(current).add(item.call_id));
    setErrors((current) => {
      const next = { ...current };
      delete next[item.call_id];
      return next;
    });
    try {
      const result = await decide.mutateAsync({ callId: item.call_id, approved });
      if (result.ok !== true) {
        setErrors((current) => ({ ...current, [item.call_id]: "该请求已处理或已失效。" }));
      }
    } catch (cause) {
      setErrors((current) => ({ ...current, [item.call_id]: toClientError(cause).message }));
    } finally {
      inFlight.current.delete(item.call_id);
      setSubmitting((current) => {
        const next = new Set(current);
        next.delete(item.call_id);
        return next;
      });
    }
  };

  return (
    <section className="mx-auto mb-3 max-h-64 w-full max-w-3xl overflow-y-auto rounded-[var(--radius-lg)] border p-3" style={{ borderColor: "var(--warn)", background: "var(--warn-tint)" }} aria-label="当前会话待审批">
      <div className="mb-2 flex items-center gap-2">
        <ShieldAlert size={15} style={{ color: "var(--warn)" }} />
        <h3 className="text-[12px] font-semibold" style={{ color: "var(--fg)" }}>
          执行已暂停，等待审批{pending.length > 1 ? `（${pending.length}）` : ""}
        </h3>
        <span className="ml-auto text-[10px]" style={{ color: "var(--fg-subtle)" }}>无需离开当前会话</span>
      </div>
      <div className="flex flex-col gap-2">
        {pending.map((item) => {
          const risk = riskMeta(item.risk, item.risk_source);
          const busy = submitting.has(item.call_id);
          return (
            <article key={item.call_id} className="rounded-[var(--radius)] border px-3 py-2.5" style={{ borderColor: "var(--border)", background: "var(--surface-overlay)" }}>
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-1.5">
                    <StatusBadge tone={risk.tone}>{risk.label}</StatusBadge>
                    <span className="font-mono text-[10px]" style={{ color: "var(--fg-subtle)" }}>{item.tool_name}</span>
                  </div>
                  <p className="select-text text-[12px] font-medium leading-relaxed" style={{ color: "var(--fg)" }}>
                    {item.message || `${item.tool_name} 请求执行`}
                  </p>
                  <p className="mt-1 truncate text-[11px]" title={item.target} style={{ color: "var(--fg-muted)" }}>
                    对象：{item.target || "未提供"} · {item.impact || "批准后继续执行"}
                  </p>
                  {errors[item.call_id] && <p className="mt-1 text-[11px]" style={{ color: "var(--danger)" }}>{errors[item.call_id]}</p>}
                </div>
                <div className="flex shrink-0 items-center gap-1.5 self-center">
                  <Button size="xs" variant="dangerGhost" disabled={busy} onClick={() => void submit(item, false)}>拒绝</Button>
                  <Button size="xs" disabled={busy} onClick={() => void submit(item, true)}>
                    {busy && <Loader2 size={12} className="animate-spin" />}
                    允许本次
                  </Button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
