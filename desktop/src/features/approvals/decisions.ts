/**
 * 本次页面会话的审批乐观记录。完整请求仅在内存中供当前页面展示；
 * 跨重启历史由服务端审计账本提供，避免把 message/target/scope 写入 WebView 存储。
 */

import { useCallback, useEffect, useState } from "react";
import type { ApprovalWire } from "@/contracts/resources";

export type DecisionOutcome = "approved" | "rejected";
export type Decision = {
  item: ApprovalWire;
  outcome: DecisionOutcome;
  at: string;
  decisionId: string;
  auditRecorded: boolean;
  entryHash: string;
};

const LEGACY_PREFIX = "vanta.approvals.decisions.";

/** 旧版曾存储完整审批请求；启动时清理所有连接分区，避免升级后继续留存。 */
export function purgeLegacyApprovalStorage(storage: Pick<Storage, "length" | "key" | "removeItem">): void {
  const keys: string[] = [];
  for (let i = 0; i < storage.length; i += 1) {
    const key = storage.key(i);
    if (key?.startsWith(LEGACY_PREFIX)) keys.push(key);
  }
  for (const key of keys) storage.removeItem(key);
}

/** 同一 call_id 只记一次；连接切换时清空内存。 */
export function useDecisionLog(connectionId: string | null) {
  const [decisions, setDecisions] = useState<Decision[]>([]);

  useEffect(() => setDecisions([]), [connectionId]);

  const record = useCallback(
    (decision: Decision) => {
      setDecisions((prev) => {
        if (prev.some((d) => d.item.call_id === decision.item.call_id)) return prev;
        return [decision, ...prev];
      });
    },
    [],
  );

  return { decisions, record };
}
