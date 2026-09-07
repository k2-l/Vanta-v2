"""Recovery node for the main LangGraph agent."""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from harness.core.foundation.errors import (
    _BACKOFF_SECONDS,
    _NON_RETRYABLE_ERRORS,
    _RECOVERY_PROMPTS,
    classify_error,
)
from harness.core.foundation.state import PenAgentState
from harness.infra.logging import log
from harness.infra.settings import get_settings


async def recovery_node(state: PenAgentState, config: RunnableConfig) -> dict:
    """错误分类 → 不可重试型直接终止；可重试型递增计数并注入提示。"""
    error = state.get("error", "") or ""
    error_type = state.get("error_type") or classify_error(error)

    # 步数软上限：迭代超限时注入进展总结请求让 LLM 询问用户；_max_iter<=0 跳过（不限）。
    _max_iter = state.get("max_tool_iterations")
    if _max_iter is None:
        _max_iter = get_settings().max_tool_iterations
    if not error and _max_iter > 0 and state.get("tool_iterations", 0) >= _max_iter:
        iterations = state.get("tool_iterations", 0)
        soft_limit_msg = HumanMessage(
            content=(
                f"[⚙系统] 已完成 {iterations} 步工具调用（当前上限 {_max_iter} 步）。\n"
                "请用中文总结当前任务进展和已完成的内容，然后询问用户：是否继续执行后续步骤？"
            )
        )
        log.info("recovery.soft_limit", iterations=iterations, max_iter=_max_iter)
        return {
            "messages": [soft_limit_msg],
            "error": None,
            "error_type": "SOFT_LIMIT_REACHED",
        }

    # 结构性错误：不消耗重试次数，由 route_after_recovery 路由到 END
    if error_type in _NON_RETRYABLE_ERRORS:
        log.warning("recovery.terminal", error_type=error_type)
        return {
            "error": error,
            "error_type": f"TERMINAL_{error_type}",
        }

    # 可重试错误：递增计数，按错误类型差异化 backoff
    attempts = state.get("recovery_attempts", 0) + 1
    backoff_list = _BACKOFF_SECONDS.get(error_type, _BACKOFF_SECONDS["UNKNOWN"])
    backoff_sec = backoff_list[min(attempts - 1, len(backoff_list) - 1)]
    if backoff_sec > 0:
        log.info("recovery.backoff", error_type=error_type, seconds=backoff_sec, attempt=attempts)
        await asyncio.sleep(backoff_sec)

    hint = _RECOVERY_PROMPTS.get(error_type, _RECOVERY_PROMPTS["UNKNOWN"])
    # HumanMessage 维持消息交替结构（Anthropic 不允许 mid-conversation SystemMessage）。
    # [⚙系统] 前缀让 LLM 识别这是内部恢复指令，而非真实用户输入。
    recovery_msg = HumanMessage(
        content=f"[⚙系统] 恢复指令 #{attempts} | 错误：{error_type}\n{hint}\n详情：{error[:300]}"
    )

    log.info("recovery", error_type=error_type, attempt=attempts)
    return {
        "messages": [recovery_msg],
        "error": None,
        "error_type": None,
        "recovery_attempts": attempts,
    }
