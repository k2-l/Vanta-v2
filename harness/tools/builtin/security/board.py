"""board 工具 —— 结果看板（BLACKBOARD P1）：多 agent 共享产出的持久库。

artifact 自动归属当前激活的 engagement（从 exec_context 读 engagement_id）——**L1 隔离**：
跨 engagement 的看板互不可见。kind 是 artifact 类别，sensitivity 是敏感级（L2 标签）。

编排中介模式（见 docs/BLACKBOARD.md）：主 agent 用 board 汇总各步产出、按需读切片注入下游子 agent。
L3 访问策略（消费者声明 ∩ 生产者 share ∩ 敏感级）与密钥 handle 分别在 P2/P3 接入。
"""

from __future__ import annotations

import json
from typing import Any

from harness.tools.base import Tool, ToolResult
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register

_KINDS = ["finding", "scan_result", "recon", "report", "note"]
_SENS = ["public", "internal", "secret"]


def _media_type(kind: str, content: str) -> str:
    """为桌面端受控预览/导出提供可信类型，不接受模型自报 MIME。"""
    if kind in {"finding", "report", "note"}:
        return "text/markdown"
    if kind in {"scan_result", "recon"}:
        try:
            json.loads(content)
        except (TypeError, ValueError):
            return "text/plain"
        return "application/json"
    return "text/plain"


@register
class BoardTool(Tool):
    name = "board"
    category = "security"
    description = (
        "结果看板：多 agent 共享产出。action：\n"
        "- write：挂一条 artifact（需 kind + title；可选 content/tags/sensitivity）；\n"
        "- read：读当前 engagement 的看板（可按 kind 过滤）。\n"
        "artifact 自动归属当前激活的 engagement，跨 engagement 不可见。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["write", "read"]},
            "kind": {"type": "string", "enum": _KINDS, "description": "artifact 类别"},
            "title": {"type": "string", "description": "标题（write 用）"},
            "content": {"type": "string", "description": "正文（write 用）"},
            "sensitivity": {
                "type": "string", "enum": _SENS,
                "description": "敏感级（write 用，默认 internal；secret 类不在此存明文，见 P3）",
            },
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（write 用）"},
        },
        "required": ["action"],
    }

    async def run(
        self,
        action: str = "",
        kind: str = "",
        title: str = "",
        content: str = "",
        sensitivity: str = "internal",
        tags: list[str] | None = None,
    ) -> ToolResult:
        from harness.infra import db

        env = get_exec_env()
        eid = env.engagement_id or None
        action = (action or "").lower()

        if action == "write":
            if kind not in _KINDS:
                return ToolResult.fail(error=f"write 需要 kind ∈ {_KINDS}", error_code="INVALID_ARGS")
            if not title:
                return ToolResult.fail(error="write 需要 title", error_code="INVALID_ARGS")
            sens = sensitivity if sensitivity in _SENS else "internal"
            rec = await db.create_artifact(
                engagement_id=eid, kind=kind, title=title, content=content,
                producer=env.session_id or "",
                source_session_id=env.session_id or "",
                media_type=_media_type(kind, content),
                sensitivity=sens,
                tags=list(tags or []),
            )
            scope = f"（归属 engagement {eid}）" if eid else "（无活跃 engagement，未归属）"
            return ToolResult(ok=True, output=f"已上看板 {rec.id} [{kind}/{sens}] {title}{scope}")

        if action == "read":
            recs = await db.list_artifacts(engagement_id=eid, kind=kind or None)
            if not recs:
                return ToolResult(ok=True, output="当前 engagement 看板为空。")
            lines = [f"看板 {len(recs)} 条" + (f" · kind={kind}" if kind else "") + "（最新在前）："]
            for r in recs:
                t = json.loads(r.tags) if r.tags else []
                tagstr = ("  #" + " #".join(t)) if t else ""
                body = (r.evidence or "").replace("\n", " ")[:120]
                lines.append(f"- {r.id} [{r.kind}/{r.sensitivity}] {r.title}{tagstr}"
                             + (f"\n    {body}" if body else ""))
            return ToolResult(ok=True, output="\n".join(lines))

        return ToolResult.fail(error=f"未知 action：{action}", error_code="INVALID_ARGS")
