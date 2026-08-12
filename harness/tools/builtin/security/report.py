"""report 工具 —— 从当前 engagement 的 findings 生成 markdown 渗透测试报告。

闭环收尾：engage → 扫描 / 审计 → finding → report。
报告含执行摘要（按严重度计数）、发现详情（证据 / 修复）、授权范围、审计动作计数。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from harness.tools.base import Tool, ToolResult
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register

_SEV = ["critical", "high", "medium", "low", "info"]


@register
class ReportTool(Tool):
    name = "report"
    category = "security"
    description = (
        "从当前 engagement 的发现(findings)生成结构化 markdown 渗透测试报告："
        "执行摘要(按严重度计数) + 发现详情(证据/修复) + 授权范围 + 审计动作计数。"
        "默认用当前激活的 engagement，可传 id 指定。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "engagement id（默认当前激活）"}},
        "required": [],
    }

    async def run(self, id: str = "") -> ToolResult:  # noqa: A002 —— 与 input_schema 键名一致
        from harness.infra import db
        from harness.security.audit_ledger import query_audit

        eid = id or get_exec_env().engagement_id
        if not eid:
            return ToolResult.fail(
                error="无 engagement（先激活一个或传 id）", error_code="INVALID_ARGS"
            )
        eng = await db.get_engagement(eid)
        if eng is None:
            return ToolResult.fail(error=f"engagement 不存在：{eid}", error_code="NOT_FOUND")

        findings = await db.list_findings(engagement_id=eid)
        findings = sorted(
            findings, key=lambda r: (_SEV.index(r.severity) if r.severity in _SEV else 9, r.created_at)
        )
        counts = {s: 0 for s in _SEV}
        for finding in findings:
            if finding.severity in counts:
                counts[finding.severity] += 1
        audit_n = len(await query_audit(engagement_id=eid, limit=5000))

        lines = [
            f"# 渗透测试报告：{eng.name}",
            "",
            f"- Engagement: `{eid}`　状态: {eng.status}",
            f"- 授权范围 (scope): {', '.join(eng.scope_targets or []) or '（空）'}",
            f"- 授权凭证: {eng.authorization_ref or '（缺）'}",
            f"- 生成时间: {datetime.now(UTC).isoformat(timespec='seconds')}",
            "",
            "## 执行摘要",
        ]
        if findings:
            summary = " · ".join(f"{s}:{counts[s]}" for s in _SEV if counts[s])
            lines.append(f"- 发现总数: {len(findings)}（{summary}）")
        else:
            lines.append("- 无发现")
        lines.append(f"- 审计动作数: {audit_n}")
        lines.append("")

        if findings:
            lines.append("## 发现详情（按严重度）")
            for finding in findings:
                cat = f"　({finding.category})" if finding.category else ""
                lines.append(f"### [{finding.severity.upper()}] {finding.title}{cat}")
                lines.append(f"- 状态: {finding.status}")
                if finding.target:
                    lines.append(f"- 目标: {finding.target}")
                if finding.evidence:
                    lines.append(f"- 证据:\n```\n{finding.evidence[:2000]}\n```")
                if finding.remediation:
                    lines.append(f"- 修复建议: {finding.remediation}")
                lines.append("")

        return ToolResult(ok=True, output="\n".join(lines))
