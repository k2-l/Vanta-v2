"""Safe logical runtime catalog for automatic Agent container selection."""

from __future__ import annotations

import json
from typing import Any

from harness.core.runtime_resolver import runtime_catalog
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register


@register
class RuntimeCatalogTool(Tool):
    name = "runtime_catalog"
    category = "runtime"
    description = (
        "列出可供子 Agent 自动选择的容器能力标签和策略。"
        "当任务需要专用运行环境且不确定 capability 标签时，先查询本工具，"
        "再把所需标签填入 Agent.runtime_requirements；不要根据镜像名猜测。"
        "已接入但异常退出的长期容器会在选中时自动启动，任务结束后继续保活。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "可选，仅返回允许该 Agent 使用的 runtime",
            }
        },
    }

    async def run(self, agent_name: str = "") -> ToolResult:
        try:
            rows = await runtime_catalog(agent_name)
            if not rows:
                return ToolResult(ok=True, output="（没有匹配且已启用的 Agent runtime）")
            return ToolResult(ok=True, output=json.dumps(rows, ensure_ascii=False, indent=2))
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                error=f"读取 Agent runtime 目录失败：{exc}",
                error_code="RUNTIME_CATALOG_ERROR",
            )
