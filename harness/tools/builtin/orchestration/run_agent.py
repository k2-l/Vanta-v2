"""run_agent 工具 — 派发任务给子 agent 独立执行。

使用场景：
  主代理调用 run_agent("代码审计专家", "审计 /src 目录", context="") 时，
  系统加载对应 AgentRecord，在独立执行上下文中运行子 agent 图，
  把最终回复文本作为工具结果返回给主代理。

串行 / 并行由主代理的 LLM 自然控制：
  - 同一条 AI 回复里的多个 run_agent 调用 → 并行（tool_node asyncio.gather）
  - 下一轮再调用 → 串行（依赖上一轮结果）
"""

from __future__ import annotations

from typing import Any

from harness.core.graph.subagent import (
    current_sub_agent_depth,
    enter_sub_agent_depth,
    run_sub_agent,
)
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register


@register
class RunAgentTool(Tool):
    name = "Agent"
    category = "agent"
    description = (
        "把一个子任务派发给指定的专家 Agent 独立执行，返回其最终输出。\n"
        "- 同一轮次多个 Agent 调用会**并行**执行\n"
        "- 需要串行时（后续任务依赖前一个结果），把前一个结果通过 context 参数传入\n"
        "- 只能调用已启动（active=true）的 Agent"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Agent 名称（如 code-audit-expert）",
            },
            "task": {
                "type": "string",
                "description": "要执行的任务描述",
            },
            "context": {
                "type": "string",
                "description": "上游 agent 的输出（串行依赖时传入），默认为空",
            },
        },
        "required": ["name", "task"],
    }

    async def run(
        self,
        name: str,
        task: str,
        context: str = "",
    ) -> ToolResult:
        from harness.agents.loader import load_agent_content
        from harness.infra.settings import get_settings

        s = get_settings()
        current_depth = current_sub_agent_depth()

        # ── 深度限制 ────────────────────────────────────────────────────
        if current_depth >= s.sub_agent_max_depth:
            return ToolResult.fail(
                error=f"已达到最大调用深度 (depth={current_depth}，上限={s.sub_agent_max_depth})，"
                f"拒绝继续派发",
                error_code="DEPTH_LIMIT",
            )

        # ── 加载 Agent 定义（单一来源，active_only 保持只派发已启动 Agent）──
        try:
            agent = await load_agent_content(name, active_only=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                error=f"加载 Agent '{name}' 时出错：{exc}",
                error_code="LOAD_ERROR",
            )
        if agent is None:
            return ToolResult.fail(
                error=f"Agent '{name}' 不存在或未启动",
                error_code="AGENT_NOT_FOUND",
            )

        # ── 递增深度，执行子 agent，执行后自动还原 ───────────────────────
        import asyncio

        import structlog

        with enter_sub_agent_depth() as new_depth:
            from harness.infra.logging import log

            log.info("run_agent.start", agent=name, depth=new_depth, task_preview=task[:80])

            # 从调用链获取 session_id / trace_id（通过 LangGraph RunnableConfig
            # 传递的 configurable 字段；未设置时降级为占位符）
            ctx = structlog.contextvars.get_contextvars()
            session_id = ctx.get("session_id", "_anon")
            trace_id = ctx.get("trace", "")

            _NON_RETRIABLE = (
                "depth",
                "budget",
                "auth",
                "permission",
                "not found",
                "not exist",
                "DEPTH_LIMIT",
                "BUDGET_LIMIT",
                "AUTH_ERROR",
                "PERMISSION",
            )

            def _is_non_retriable(exc: Exception) -> bool:
                msg = str(exc).lower()
                return any(k.lower() in msg for k in _NON_RETRIABLE)

            max_attempts = 3
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result_text = await run_sub_agent(
                        agent=agent,
                        task=task,
                        context=context,
                        depth=new_depth,
                        session_id=session_id,
                        trace_id=trace_id,
                    )
                    log.info(
                        "run_agent.done", agent=name, depth=new_depth, output_len=len(result_text)
                    )
                    return ToolResult(ok=True, output=result_text)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if _is_non_retriable(exc):
                        log.error(
                            "run_agent.error", agent=name, attempt=attempt, exc=str(exc)[:300]
                        )
                        return ToolResult.fail(
                            error=f"子 Agent '{name}' 执行失败：{exc}",
                            error_code="SUB_AGENT_ERROR",
                        )
                    if attempt < max_attempts:
                        wait = 2 ** (attempt - 1)
                        log.warning(
                            "run_agent.retry",
                            agent=name,
                            attempt=attempt,
                            reason=str(exc)[:200],
                            wait_seconds=wait,
                        )
                        await asyncio.sleep(wait)

            log.error("run_agent.error", agent=name, attempt=max_attempts, exc=str(last_exc)[:300])
            return ToolResult.fail(
                error=f"子 Agent '{name}' 执行失败（已重试 3 次）：{last_exc}",
                error_code="SUB_AGENT_ERROR",
            )
