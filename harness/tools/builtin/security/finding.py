"""finding 工具 —— 记录 / 列出 / 分诊安全发现，供报告汇总。

发现自动归属当前激活的 engagement（从 exec_context 读 engagement_id），
带严重度 / 证据 / 修复建议 / FP 分诊。
"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool, ToolResult
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register

_SEV = ["critical", "high", "medium", "low", "info"]
_STATUS = ["open", "triaged", "false_positive", "fixed"]


@register
class FindingTool(Tool):
    name = "finding"
    category = "security"
    description = (
        "记录 / 查看安全发现（漏洞·弱点）。action：\n"
        "- record：记一条发现（需 title + severity[critical/high/medium/low/info]；"
        "可选 category(如 CWE-89)/target/evidence/remediation）；\n"
        "- list：列出当前 engagement 的发现（按严重度排序）；\n"
        "- triage：改状态（需 id + status[open/triaged/false_positive/fixed]）。\n"
        "发现自动归属当前激活的 engagement。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["record", "list", "triage"]},
            "id": {"type": "string", "description": "finding id（triage 用）"},
            "title": {"type": "string", "description": "发现标题（record 用）"},
            "severity": {"type": "string", "enum": _SEV, "description": "严重度（record 用）"},
            "category": {"type": "string", "description": "分类，如 CWE-89 / OWASP-A03（record 用）"},
            "target": {"type": "string", "description": "受影响目标/位置（record 用）"},
            "evidence": {"type": "string", "description": "证据/复现（record 用）"},
            "remediation": {"type": "string", "description": "修复建议（record 用）"},
            "status": {"type": "string", "enum": _STATUS, "description": "分诊状态（triage 用）"},
        },
        "required": ["action"],
    }

    async def run(
        self,
        action: str = "",
        id: str = "",  # noqa: A002 —— 需与 input_schema 键名一致
        title: str = "",
        severity: str = "info",
        category: str = "",
        target: str = "",
        evidence: str = "",
        remediation: str = "",
        status: str = "",
    ) -> ToolResult:
        from harness.infra import db

        env = get_exec_env()
        eid = env.engagement_id or None
        action = (action or "").lower()

        if action == "record":
            if not title:
                return ToolResult.fail(error="record 需要 title", error_code="INVALID_ARGS")
            sev = severity.lower() if severity.lower() in _SEV else "info"
            rec = await db.create_finding(
                engagement_id=eid, title=title, severity=sev, category=category,
                target=target, evidence=evidence, remediation=remediation,
            )
            scope = f"（归属 engagement {eid}）" if eid else "（无活跃 engagement，未归属）"
            return ToolResult(ok=True, output=f"已记录发现 {rec.id} [{sev}] {title}{scope}")

        if action == "list":
            recs = await db.list_findings(engagement_id=eid)
            if not recs:
                return ToolResult(ok=True, output="当前 engagement 暂无发现。")
            recs = sorted(
                recs, key=lambda r: (_SEV.index(r.severity) if r.severity in _SEV else 9, r.created_at)
            )
            lines = [f"共 {len(recs)} 条发现（按严重度）："]
            for r in recs:
                extra = (f"  {r.category}" if r.category else "") + (f"  →{r.target}" if r.target else "")
                lines.append(f"- {r.id} [{r.severity}] [{r.status}] {r.title}{extra}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "triage":
            if not id or not status:
                return ToolResult.fail(error="triage 需要 id 和 status", error_code="INVALID_ARGS")
            st = status.lower()
            if st not in _STATUS:
                return ToolResult.fail(error=f"status 须为 {_STATUS}", error_code="INVALID_ARGS")
            ok = await db.set_finding_status(id, st)
            if not ok:
                return ToolResult.fail(error=f"发现不存在：{id}", error_code="NOT_FOUND")
            return ToolResult(ok=True, output=f"发现 {id} 状态 → {st}")

        return ToolResult.fail(error=f"未知 action：{action}", error_code="INVALID_ARGS")
