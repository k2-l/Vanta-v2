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
  /** 权威风险等级（后端派生/工具声明）；risk_source 区分二者，前端如实展示。 */
  risk?: "critical" | "high" | "medium" | "low" | (string & {});
  /** "declared"=工具显式声明；"derived"=按 category 回退（前端标注"派生"）。 */
  risk_source?: "declared" | "derived" | (string & {});
  /** 操作对象（从工具入参提取）。 */
  target?: string;
  /** 作用范围（执行位置 + 授权 engagement）。 */
  scope?: string;
  /** 预计影响（按风险等级派生）。 */
  impact?: string;
};

/**
 * 审批决策历史项（GET /chat/approvals/history）——来自哈希链审计账本的服务端权威记录，
 * 进程重启后仍可查询（区别于 localStorage 的本机记录）。
 * decision_id 为独立稳定 id；entry_hash 是审计证据（哈希链条目），失败时为空串。
 */
export type ApprovalDecisionRecord = {
  decision_id: string;
  call_id: string;
  tool_name: string;
  session_id: string;
  decision: "approved" | "rejected" | "expired";
  risk?: string;
  risk_source?: string;
  target?: string;
  scope?: string;
  impact?: string;
  message?: string;
  requested_at?: string;
  expires_at?: string;
  decided_at: string;
  audit_recorded?: boolean;
  entry_hash?: string;
};

/** POST /chat/approvals/{call_id} 决策响应。 */
export type ApprovalDecisionResult = {
  ok: boolean;
  decision_id: string;
  decision: "approved" | "rejected";
  /** 审计是否成功入账；false 表示决策生效但审计写入失败（entry_hash 为空）。 */
  audit_recorded: boolean;
  entry_hash: string;
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
  /** 后端按 UTF-8 正文计算；secret 也只暴露大小，不暴露正文。 */
  size_bytes?: number;
  media_type?: string;
  /** 当前 run≈session，后端仍显式返回两个字段，避免继续猜 producer。 */
  source_session_id?: string;
  source_run_id?: string;
  tags?: string[];
  vault_ref?: string;
  severity?: string;
  status?: string;
  created_at?: string | null;
  updated_at?: string | null;
};
