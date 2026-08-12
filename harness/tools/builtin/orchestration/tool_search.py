"""tool_search 工具 —— 动态工具池的按需检索与披露入口（static，常驻绑定）。

背景：声明式 CLI 工具（workspace/tools/*.toml）与 MCP 工具设为 disclosure="dynamic"，
不直接绑定给模型，否则每装一个就往每轮 prompt 里塞一份完整参数 schema，token 膨胀。
它们藏在本工具之后：模型先用关键词 tool_search，命中工具会被写进 graph state 的
「已披露集」（disclosed_tools），下一轮 agent 节点 rebind 时才把这些工具绑上，模型方可真正调用。

匹配为简单子串/关键词（名称+描述），不做语义检索 —— 与 registry.match_dynamic() 单一来源。
本工具只负责生成给模型看的清单文本；真正把命中名累加进 disclosed_tools 的副作用在
两个 tool_node 里完成（它们对同一 (query, limit) 复算 match_dynamic，结果与此处一致，
无需解析本工具输出即可对齐「披露」与「可绑定」）。借鉴 CyberStrikeAI 的 eino toolsearch
中间件（Apache-2.0，github.com/Ed1s0nZ/CyberStrikeAI），转译为 LangGraph 惯用法。
"""

from __future__ import annotations

import json
from typing import Any

from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register, registry


def _schema_summary(input_schema: dict[str, Any]) -> str:
    """把 input_schema 压成一行参数摘要：name(type)[*必填]，供模型判断是否需要该工具。"""
    props = (input_schema or {}).get("properties") or {}
    required = set((input_schema or {}).get("required") or [])
    if not props:
        return "(无参数)"
    parts: list[str] = []
    for pname, pdef in props.items():
        ptype = (pdef or {}).get("type", "string")
        star = "*" if pname in required else ""
        parts.append(f"{pname}({ptype}){star}")
    return ", ".join(parts)


@register
class ToolSearchTool(Tool):
    name = "tool_search"
    category = "orchestration"
    # 常驻绑定：本工具是进入动态工具池的唯一入口，必须始终对模型可见。
    disclosure = "static"
    description = (
        "按关键词/意图搜索「未直接列出」的专用工具（声明式 CLI 如 nmap、MCP 工具等）。\n"
        "这些工具不常驻在工具列表里，需要时先用本工具搜索；命中的工具会在**下一轮**"
        "对话被解锁并附上完整参数定义，届时才能真正调用。\n"
        "在未通过本工具看到某工具的参数 schema 前，禁止凭工具名臆测参数直接调用。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "关键词或意图，如 'nmap'、'端口扫描'、'mcp filesystem'；留空则列出全部可披露工具",
            },
            "limit": {
                "type": "integer",
                "description": "最多返回多少个命中工具，默认 10",
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str = "", limit: int = 10) -> ToolResult:
        specs = {s["name"]: s["description"] for s in registry.dynamic_specs()}
        if not specs:
            # 回退：dynamic 池为空（没装声明式/MCP 工具），行为等价现状（全 static）。
            return ToolResult(
                ok=True,
                output="当前没有可披露的动态工具（未配置声明式 CLI 工具或 MCP 工具）。",
            )

        hit_names = registry.match_dynamic(query, limit)
        if not hit_names:
            return ToolResult(
                ok=True,
                output=(
                    f"没有匹配 {query!r} 的工具。当前可披露的动态工具共 {len(specs)} 个，"
                    "可换关键词或留空 query 查看全部。"
                ),
            )

        lines: list[str] = [
            f"已匹配 {len(hit_names)} 个工具，它们将在下一轮对话解锁（附完整参数定义）后可调用：",
        ]
        for name in hit_names:
            tool = registry.get(name)
            lines.append(f"\n## {name}")
            lines.append((tool.description or specs.get(name, "")).strip())
            lines.append(f"参数：{_schema_summary(tool.input_schema)}")

        # 附一份机器可读的命中名列表，便于日志/排查（tool_node 不依赖它解析，复算 match_dynamic）。
        lines.append("\n" + json.dumps({"disclosed": hit_names}, ensure_ascii=False))
        return ToolResult(ok=True, output="\n".join(lines))
