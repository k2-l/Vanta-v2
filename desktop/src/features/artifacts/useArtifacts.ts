/**
 * 产物数据层（Plan G3）——看板 artifact 只读列表（GET /v1/artifacts）。
 * secret 类不回明文正文（后端只留 vault_ref），前端据此只显示元数据（规范 §4.4）。
 * 写侧/导出不在此暴露：artifact 仅由 agent 的 board 工具产出，导出受 capability 门控。
 */

import { useQuery } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import type { ArtifactWire } from "@/contracts/resources";
import type { Tone } from "@/components/desktop/status";
import type { PreviewKind } from "@/components/desktop";

export function useArtifacts(kind?: string) {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  return useQuery<ArtifactWire[]>({
    queryKey: ["artifacts", connectionId, kind ?? "all"],
    enabled: Boolean(connectionId && authed),
    staleTime: 15_000,
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "artifacts.list", kind },
      });
      return Array.isArray(result) ? (result as ArtifactWire[]) : [];
    },
  });
}

const KIND_LABEL: Record<string, string> = {
  finding: "发现",
  note: "笔记",
  report: "报告",
  log: "日志",
  evidence: "证据",
  plan: "计划",
  artifact: "产物",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

export function sensitivityMeta(s: string): { label: string; tone: Tone } {
  if (s === "secret") return { label: "机密", tone: "danger" };
  if (s === "public") return { label: "公开", tone: "ok" };
  return { label: "内部", tone: "neutral" };
}

const SEVERITY: Record<string, { label: string; tone: Tone }> = {
  critical: { label: "严重", tone: "danger" },
  high: { label: "高", tone: "danger" },
  medium: { label: "中", tone: "warn" },
  low: { label: "低", tone: "ok" },
  info: { label: "信息", tone: "neutral" },
};

export function severityMeta(s?: string) {
  return s ? SEVERITY[s] : undefined;
}

export function isSecret(a: ArtifactWire): boolean {
  return a.sensitivity === "secret";
}

export function previewKindFor(a: ArtifactWire): PreviewKind {
  if (isSecret(a) || !a.content) return "none";
  return "markdown"; // evidence 为自由文本正文，按 Markdown 渲染。
}
