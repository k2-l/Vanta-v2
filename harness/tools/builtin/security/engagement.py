"""engagement 工具 —— 对话式管理授权范围（创建 / 激活 / 列出 / 结束）。

激活后本会话的主动扫描 / 渗透受此 scope 约束（scope 门 + 沙箱 egress + 审计留痕）、越界物理不可达。
scope 匹配 / 有效期逻辑见 infra/engagement.py，持久化见 db.py。
"""

from __future__ import annotations

from typing import Any

from harness.security import engagement as eng_logic
from harness.tools.base import Tool, ToolResult
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register


@register
class EngagementTool(Tool):
    name = "engagement"
    category = "security"
    description = (
        "管理授权测试范围（engagement）。action：\n"
        "- create：建 engagement（需 name + targets 域名/IP/CIDR 列表 + authorization_ref 授权凭证）；\n"
        "- activate：激活某 engagement 为当前会话的授权范围（需 id）；\n"
        "- list：列出所有 engagement；\n"
        "- end：结束某 engagement 并清理沙箱/凭据/输出（需 id）。\n"
        "激活后本会话的主动扫描/渗透受该 scope 约束（越界物理不可达 + 审计留痕）。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "activate", "list", "end"]},
            "id": {"type": "string", "description": "engagement id（activate / end 用）"},
            "name": {"type": "string", "description": "engagement 名（create 用）"},
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "授权范围：域名 / IP / CIDR / repo 列表（create 用）",
            },
            "authorization_ref": {
                "type": "string",
                "description": "授权凭证引用：授权书 / CTF 规则 / scope 批准（激活前置硬门）",
            },
        },
        "required": ["action"],
    }

    async def run(
        self,
        action: str = "",
        id: str = "",  # noqa: A002 —— 需与 input_schema 键名一致
        name: str = "",
        targets: list[str] | None = None,
        authorization_ref: str = "",
    ) -> ToolResult:
        from harness.infra import db

        action = (action or "").lower()

        if action == "create":
            if not name or not targets:
                return ToolResult.fail(error="create 需要 name 和 targets", error_code="INVALID_ARGS")
            valid, invalid = eng_logic.validate_scope(list(targets))
            if not valid:
                return ToolResult.fail(error=f"targets 全部非法：{invalid}", error_code="INVALID_ARGS")
            rec = await db.create_engagement(name, valid, authorization_ref=authorization_ref)
            warn = f"（已忽略非法条目：{invalid}）" if invalid else ""
            auth = "有" if authorization_ref else "缺（激活前必须补授权凭证）"
            return ToolResult(
                ok=True,
                output=(
                    f"已建 engagement {rec.id}：{name}\n  scope={valid}{warn}\n"
                    f"  状态=draft，authorization_ref={auth}\n"
                    f'  用 engagement(action="activate", id="{rec.id}") 激活'
                ),
            )

        if action == "activate":
            if not id:
                return ToolResult.fail(error="activate 需要 id", error_code="INVALID_ARGS")
            rec = await db.get_engagement(id)
            if rec is None:
                return ToolResult.fail(error=f"engagement 不存在：{id}", error_code="NOT_FOUND")
            eng = eng_logic.Engagement(
                id=rec.id, name=rec.name, scope_targets=list(rec.scope_targets or []),
                status="active", authorization_ref=rec.authorization_ref,
                starts_at=rec.starts_at, ends_at=rec.ends_at,
            )
            ok, reason = eng_logic.is_engagement_active(eng)
            if not ok:
                return ToolResult.fail(error=f"不能激活：{reason}", error_code="NOT_ALLOWED")
            await db.set_engagement_status(id, "active")
            sid = get_exec_env().session_id
            if sid:
                await db.set_active_engagement(sid, id)
            return ToolResult(
                ok=True,
                output=(
                    f"已激活 engagement {id}：{rec.name}\n  scope={rec.scope_targets}\n"
                    "  本会话的主动动作现受此 scope 约束（越界物理不可达 + 审计留痕）。"
                ),
            )

        if action == "list":
            recs = await db.list_engagements()
            if not recs:
                return ToolResult(ok=True, output='暂无 engagement。用 engagement(action="create", ...) 新建。')
            sid = get_exec_env().session_id
            active_id = await db.get_active_engagement_id(sid) if sid else ""
            lines = [f"共 {len(recs)} 个 engagement："]
            for r in recs:
                mark = "  ← 本会话激活中" if r.id == active_id else ""
                lines.append(f"- {r.id} [{r.status}] {r.name}  scope={r.scope_targets}{mark}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "end":
            if not id:
                return ToolResult.fail(error="end 需要 id", error_code="INVALID_ARGS")
            await db.set_engagement_status(id, "ended")
            try:  # 收尾：拆沙箱 + 清凭据/输出
                from harness.security import output_vault, sandbox, secrets_vault

                await sandbox.teardown_engagement(id)
                secrets_vault.delete_engagement_secrets(id)
                output_vault.purge_engagement_outputs(id)
            except Exception:  # noqa: BLE001 —— 收尾尽力而为，单项失败不阻断
                pass
            sid = get_exec_env().session_id
            if sid and await db.get_active_engagement_id(sid) == id:
                await db.set_active_engagement(sid, "")
            return ToolResult(ok=True, output=f"已结束 engagement {id}，并清理沙箱/凭据/输出。")

        return ToolResult.fail(error=f"未知 action：{action}", error_code="INVALID_ARGS")
