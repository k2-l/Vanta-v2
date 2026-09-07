"""LangGraph routing helpers for main and sub-agent graphs.

Keeping routing predicates in this module makes the graph topology files focus on
node registration and edge wiring, while tests can exercise branch priority
without importing or compiling full graphs.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage
from langgraph.graph import END

from harness.core.foundation.state import PenAgentState, SubAgentState
from harness.infra.metrics import inc as _inc
from harness.infra.settings import get_settings

# ─── 主图简单路由表（单字段 → 目标节点）──────────────────────────────
# 格式：router_key → {state_value → next_node}
# 仅覆盖两个纯双分支路由；多条件路由（agent / recovery）保留完整函数。

_ROUTE_TABLE: dict[str, dict[str, str]] = {
    # error_type 前缀为 "BUDGET_" → END，否则 → "agent"
    "preprocess": {
        "BUDGET_": END,  # startswith 检查，见 _route 实现
        "__default__": "agent",
    },
}


def _route(router_key: str, state: PenAgentState) -> str:
    """通用路由查表函数（当前仅 preprocess 使用）。

    - preprocess：检查 error_type 是否以 "BUDGET_" 开头
    """
    table = _ROUTE_TABLE[router_key]
    error_type = state.get("error_type") or ""

    matched = "__default__"
    for key in table:
        if key != "__default__" and error_type.startswith(key):
            matched = key
            break

    return table[matched]


# ─── 主图路由函数 ───────────────────────────────────────────────────


def route_after_agent(state: PenAgentState) -> str:
    """agent 节点后的分支判断。优先级：错误 > 工具循环 > 有工具调用 > 完成

    上下文压缩已移出自动流程（改为用户主动触发），此处不再有 token 超阈值 → summarize 分支。
    """
    # 1. 有错误 → 无条件交给 recovery；是否还有次数由 recovery 节点自己决定
    if state.get("error"):
        _inc("route.agent.recovery")
        return "recovery"

    messages = state.get("messages", [])
    last = messages[-1] if messages else None

    # 2. 有 tool_call → 工具循环检测（超限 → recovery 打断循环）
    if isinstance(last, AIMessage) and last.tool_calls:
        iterations = state.get("tool_iterations", 0)
        max_iter = state.get("max_tool_iterations", 20)  # <=0 不限
        if max_iter > 0 and iterations >= max_iter:
            _inc("route.agent.tool_loop")
            return "recovery"
        _inc("route.agent.tools")
        return "tools"

    _inc("route.agent.end")
    return END


def route_after_preprocess(state: PenAgentState) -> str:
    """preprocess 节点后：预算耗尽时提前终止，避免无效 LLM 调用。"""
    dest = _route("preprocess", state)
    if dest == END:
        _inc("route.preprocess.budget_exceeded")
    else:
        _inc("route.preprocess.ok")
    return dest


def route_after_recovery(state: PenAgentState) -> str:
    """recovery 节点后：不可重试型或次数耗尽 → END，否则重试。"""
    error_type = state.get("error_type") or ""
    if error_type.startswith("TERMINAL_"):
        _inc("route.recovery.terminal")
        return END
    # 软上限：agent 总结进展并询问用户是否继续，之后正常结束
    if error_type == "SOFT_LIMIT_REACHED":
        _inc("route.recovery.soft_limit")
        return "agent"
    if state.get("recovery_attempts", 0) >= state.get(
        "max_recovery_attempts", get_settings().max_recovery_attempts
    ):
        _inc("route.recovery.exhausted")
        return END
    _inc("route.recovery.retry")
    return "agent"


# ─── 子图路由函数 ───────────────────────────────────────────────────


def build_sub_agent_route_after_agent(enable_critic: bool) -> Callable[[SubAgentState], str]:
    """返回子 agent 节点后的路由函数。

    enable_critic=True 时，无 tool_call 的最终回复先经过 critic 质量门；
    enable_critic=False 时直接 END。
    """

    def route_after_sub_agent(state: SubAgentState) -> str:
        if state.get("error"):
            return "recovery"
        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage) and last.tool_calls:
            _mi = state.get("max_tool_iterations", 10)
            if _mi > 0 and state.get("tool_iterations", 0) >= _mi:
                return "recovery"
            return "tools"
        if enable_critic:
            return "critic"
        return END

    return route_after_sub_agent


def route_after_sub_agent_critic(state: SubAgentState) -> str:
    """critic 通过或已耗尽重试（critic_passed=True）→ END；否则回 agent 重试。"""
    if state.get("critic_passed"):
        return END
    return "agent"


def route_after_sub_agent_recovery(state: SubAgentState) -> str:
    """子 agent recovery 后：终止错误或次数耗尽 → END，否则回 agent。"""
    error_type = state.get("error_type") or ""
    if error_type.startswith("TERMINAL_"):
        return END
    if error_type == "SOFT_LIMIT_REACHED":
        return "agent"
    if state.get("recovery_attempts", 0) >= state.get("max_recovery_attempts", 2):
        return END
    return "agent"
