/**
 * REST 资源契约（Plan §5：Approval / Artifact）——与后端形状逐字段对齐。
 * Approval：GET /chat/approvals 列表项；决策 POST /chat/approvals/{call_id} {approved}。
 * Artifact：GET /v1/artifacts 列表项（harness `_utils.artifact_to_dict`）。
 */

/** 挂起审批（harness/security/approvals.py list_pending）。 */
export type ApprovalWire = {
  call_id: string;
  tool_name: string;
  message: string;
  session_id: string;
  requested_at: string;
  expires_at: string;
};

/** 看板 artifact（secret 类 content 为空串，只留 vault_ref）。 */
export type ArtifactWire = {
  id: string;
  engagement_id?: string | null;
  producer?: string;
  kind: string;
  sensitivity: "public" | "internal" | "secret" | (string & {});
  title: string;
  content?: string;
  tags?: string[];
  vault_ref?: string;
  severity?: string;
  status?: string;
  created_at?: string | null;
};
