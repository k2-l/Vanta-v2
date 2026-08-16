"""load_skill / load_agent 工具 — L2 层按需加载。

L2 加载内容：
  - SOP（标准操作流程）：skill 的完整正文
  - 推荐工具：allowed_tools 字段 + 依赖知识库
  - 执行顺序：从 SOP 中提取的步骤摘要
"""
from __future__ import annotations

<<<<<<< HEAD
import json
=======
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
import re
from typing import Any

from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register


def _parse_sections(content: str) -> dict[str, str]:
    """将 markdown 正文按 ## 标题拆分为命名的段。"""
    sections: dict[str, str] = {}
    current_title = "_header"
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections[current_title] = "\n".join(current_lines).strip()
<<<<<<< HEAD
            current_title = line.strip("## #").strip()
=======
            current_title = line.strip("# ").strip()
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _extract_steps(content: str) -> list[str]:
    """从正文中提取编号步骤（### N. 或 - N. 格式）。"""
    steps: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if re.match(r"^(#+|\d+[.)]|[-*])\s", stripped):
            steps.append(stripped)
    return steps[:15]  # 最多 15 步


def _build_l2_block(
    name: str,
    description: str,
    content: str,
    allowed_tools: list[str],
    dependencies: list[dict[str, str]],
    argument_hint: str = "",
) -> str:
    """构建 L2 结构化响应。"""
    sections = _parse_sections(content)
    steps = _extract_steps(content)

    lines = [f"## Skill: {name}（L2 加载）", ""]

    # 描述
    lines.append(f"### 描述\n{description}\n")

    # 调用参数说明
    if argument_hint:
        lines.append(f"### 调用参数说明\n{argument_hint}\n")

    # 推荐工具
    tools = list(allowed_tools)
    if not tools:
        tools.append("（无预设工具限制）")
<<<<<<< HEAD
    lines.append(f"### 推荐工具\n- " + "\n- ".join(tools))
=======
    lines.append("### 推荐工具\n- " + "\n- ".join(tools))
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

    # 依赖知识库
    kb_deps = [d["dep_name"] for d in dependencies if d.get("dep_kind") == "inrepository"]
    if kb_deps:
        lines.append("")
        lines.append("### 依赖知识库\n- " + "\n- ".join(kb_deps))

    # 执行顺序
    if steps:
        lines.append("")
        lines.append("### 执行顺序")
        lines.extend(f"{s}" for s in steps)

    # SOP 正文（排除已提取的步骤标题）
    body_parts = []
    for title, body in sections.items():
        if title == "_header":
            continue
        body_parts.append(f"### {title}\n{body}")
    if body_parts:
        lines.append("")
        lines.append("### SOP（标准操作流程）")
        lines.append("\n\n".join(body_parts))

    return "\n".join(lines)


@register
class LoadSkillTool(Tool):
    name = "Skill"
    category = "skill"
    description = (
<<<<<<< HEAD
        "加载一个**已启动的 Skill** 的完整内容（L2 层：SOP + 推荐工具 + 执行顺序）。"
        "当你判断当前任务符合某个 Skill 的用途时调用，获取详细指令后再执行。"
        "只能加载已启动（active=true）的 Skill。"
=======
        "加载一个 Skill 的完整内容（L2 层：SOP + 推荐工具 + 执行顺序）。"
        "当你判断当前任务符合某个 Skill 的用途时调用，获取详细指令后再执行。"
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill 的名称（如 java-audit）",
            }
        },
        "required": ["name"],
    }

    async def run(self, name: str) -> ToolResult:
<<<<<<< HEAD
        from harness.infra.db import EntityDependency, SkillRecord, session_factory
        from sqlalchemy import select

        try:
            async with session_factory()() as db:
                rec = (
                    await db.execute(
                        select(SkillRecord).where(
                            SkillRecord.name == name,
                            SkillRecord.active == True,  # noqa: E712
                        )
                    )
                ).scalar_one_or_none()

                if rec is None:
                    return ToolResult(
                        ok=False,
                        output="",
                        error=f"Skill '{name}' 不存在或未启动",
                    )

                # 加载依赖知识库（用于工具推荐）
                dep_rows = (
                    await db.execute(
                        select(EntityDependency)
                        .where(
                            EntityDependency.source_name == name,
                            EntityDependency.source_type == "skill",
                        )
                    )
                ).scalars().all()

            allowed_tools = json.loads(rec.allowed_tools) if rec.allowed_tools else []
            deps = [
                {"dep_kind": d.dep_kind, "dep_name": d.dep_name}
                for d in dep_rows
            ]

            output = _build_l2_block(
                name=rec.name,
                description=rec.description,
                content=rec.content,
                allowed_tools=allowed_tools,
                dependencies=deps,
                argument_hint=rec.argument_hint or "",
            )
            return ToolResult(ok=True, output=output)

        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=str(exc))

=======
        from harness.providers import get_provider

        try:
            full = get_provider("skill").get(name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=str(exc))

        if full is None:
            return ToolResult(ok=False, output="", error=f"Skill '{name}' 不存在")

        output = _build_l2_block(
            name=full.meta.name,
            description=full.meta.description,
            content=full.content,
            allowed_tools=full.allowed_tools,
            dependencies=[],
            argument_hint=full.argument_hint or "",
        )
        if full.path:
            output += (
                "\n\n### 附带文件（L3 渐进披露）\n"
                f"此 Skill 目录：`{full.path}`——如正文引用了 references/ 脚本等，用文件工具按需打开。"
            )
        return ToolResult(ok=True, output=output)

>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

def _build_agent_l2_block(
    name: str,
    description: str,
    triggers: list[str],
    argument_hint: str,
    tools: list[str],
) -> str:
    """构建 Agent L2 结构化响应（按需加载元数据，不含 content 正文）。"""
    lines = [f"## Agent: {name}（L2 加载）", ""]

    # 描述
    lines.append(f"### 描述\n{description}\n")

    # 触发时机
    if triggers:
        lines.append("### 触发时机")
        lines.extend(f"- {t}" for t in triggers)
        lines.append("")
    else:
        lines.append("### 触发时机\n（无预设触发词）\n")

    # 调用参数说明
    if argument_hint:
        lines.append(f"### 调用参数\n{argument_hint}\n")

    # 允许工具列表
    tool_list = list(tools) if tools else ["（无预设工具限制）"]
    lines.append("### 允许工具\n- " + "\n- ".join(tool_list))

    return "\n".join(lines)


@register
class LoadAgentTool(Tool):
    name = "load_agent"
    category = "agent"
    description = (
<<<<<<< HEAD
        "加载一个**已启动的 Agent** 的完整 system prompt（L2 层）。"
        "当你需要以特定 Agent 的角色/专业能力执行任务时调用。"
        "只能加载已启动（active=true）的 Agent。"
=======
        "加载一个 Agent 的完整 system prompt（L2 层）。"
        "当你需要以特定 Agent 的角色/专业能力执行任务时调用。"
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Agent 的名称（如 audit-analyst）",
            }
        },
        "required": ["name"],
    }

    async def run(self, name: str) -> ToolResult:
<<<<<<< HEAD
        from harness.infra.db import AgentRecord, session_factory
        from sqlalchemy import select

        try:
            async with session_factory()() as db:
                rec = (
                    await db.execute(
                        select(AgentRecord).where(
                            AgentRecord.name == name,
                            AgentRecord.active == True,  # noqa: E712
                        )
                    )
                ).scalar_one_or_none()

                if rec is None:
                    return ToolResult(
                        ok=False,
                        output="",
                        error=f"Agent '{name}' 不存在或未启动",
                    )

            tools = json.loads(rec.tools) if rec.tools else []
            triggers = json.loads(rec.triggers) if rec.triggers else []
            output = _build_agent_l2_block(
                name=rec.name,
                description=rec.description,
                triggers=triggers,
                argument_hint=rec.argument_hint or "",
                tools=tools,
            )
            return ToolResult(ok=True, output=output)

        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=str(exc))
=======
        from harness.providers import get_provider

        try:
            full = get_provider("agent").get(name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=str(exc))

        if full is None:
            return ToolResult(ok=False, output="", error=f"Agent '{name}' 不存在")

        output = _build_agent_l2_block(
            name=full.meta.name,
            description=full.meta.description,
            triggers=[],
            argument_hint="",
            tools=full.tools,
        )
        return ToolResult(ok=True, output=output)
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
