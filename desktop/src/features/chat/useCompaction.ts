/**
 * 会话主动压缩数据层——预览（不落库）+ 提交（写检查点）。
 *
 * 两步式，对齐后端 harness/routes/sessions.py：
 *   1. preview：把截至此刻的原文压成结构化摘要返回，供用户确认/编辑，不落库；
 *   2. commit ：把（可能编辑过的）摘要 + upto 检查点写入会话。原文始终保留、可回退。
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import type { CompactionPreview } from "@/contracts/chat";

/** 生成压缩预览（POST /sessions/{id}/compress/preview）。 */
export function useCompactionPreview() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  return useMutation<CompactionPreview, unknown, { sessionId: string }>({
    mutationFn: (v) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.compress.preview", sessionId: v.sessionId },
      }) as Promise<CompactionPreview>,
  });
}

/** 提交压缩（POST /sessions/{id}/compress/commit）。summary 可为用户编辑后的文本。 */
export function useCompactionCommit() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const qc = useQueryClient();
  return useMutation<void, unknown, { sessionId: string; summary: string; upto: string }>({
    mutationFn: (v) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: {
          op: "sessions.compress.commit",
          sessionId: v.sessionId,
          summary: v.summary,
          upto: v.upto,
        },
      }) as Promise<void>,
    onSuccess: (_data, v) => {
      // 原文与 transcript 不变；压缩改变的是后续运行装载的历史 + token 预算。
      qc.invalidateQueries({ queryKey: ["budget", connectionId, v.sessionId] });
    },
  });
}
