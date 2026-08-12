/**
 * ApprovalPrompt — HITL 工具审批门（item 6）。
 *
 * 渲染 chat store 中的 pendingApprovals（由后端通过 WS 推送的
 * approval_required 事件填充，见 harness/infra/approvals.py）。
 * 用户点击"批准"/"拒绝"后调用 POST /chat/approvals/{call_id}，
 * 并立即从列表中移除——resolve_approval 是幂等的，若请求已超时失效
 * 则后端返回 404，这里静默忽略（用户的操作结果已无意义）。
 */
import { useState } from "react";
import { ShieldAlert } from "lucide-react";
import { useChat } from "@/store/chat";
import { api } from "@/shared/lib/api";

export function ApprovalPrompt() {
  const pendingApprovals = useChat((s) => s.pendingApprovals);

  if (pendingApprovals.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {pendingApprovals.map((a) => (
        <ApprovalCard key={a.call_id} {...a} />
      ))}
    </div>
  );
}

function ApprovalCard({ call_id, tool_name, message }: { call_id: string; tool_name: string; message: string }) {
  const dismissApproval = useChat((s) => s.dismissApproval);
  const [submitting, setSubmitting] = useState(false);

  async function decide(approved: boolean) {
    setSubmitting(true);
    try {
      await api.submitApproval(call_id, approved);
    } catch {
      // 忽略：可能已超时失效（404），UI 仍按用户操作移除
    } finally {
      dismissApproval(call_id);
    }
  }

  return (
    <div style={{
      marginTop: 2,
      marginBottom: 2,
      overflow: "hidden",
      borderRadius: 8,
      border: "1px solid #FDE68A",
      background: "#FFFBEB",
      fontSize: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px" }}>
        <ShieldAlert style={{ width: 12, height: 12, flexShrink: 0, color: "#F59E0B" }} />
        <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#F59E0B" }}>{tool_name}</span>
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#9BA3AF" }}>
          {message}
        </span>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button
            onClick={() => decide(true)}
            disabled={submitting}
            style={{
              fontSize: 11, padding: "4px 12px", borderRadius: 6,
              background: "#10B98111", border: "1px solid #10B98144",
              color: "#10B981", cursor: submitting ? "default" : "pointer", fontFamily: "inherit",
              opacity: submitting ? 0.5 : 1,
            }}
          >
            ✓ 批准
          </button>
          <button
            onClick={() => decide(false)}
            disabled={submitting}
            style={{
              fontSize: 11, padding: "4px 12px", borderRadius: 6,
              background: "#EF444411", border: "1px solid #EF444444",
              color: "#EF4444", cursor: submitting ? "default" : "pointer", fontFamily: "inherit",
              opacity: submitting ? 0.5 : 1,
            }}
          >
            ✗ 拒绝
          </button>
        </div>
      </div>
    </div>
  );
}
