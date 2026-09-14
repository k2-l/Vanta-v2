"""build — 子 agent 轻量 StateGraph 的组装。

拓扑：
  START → agent → [tools → agent]* → END
                ↘ recovery → agent* → END

与主代理图的区别：
  - 无 preprocess（子 agent 不加载记忆/画像/skill 上下文）
  - 无 summarize（子 agent 任务有界，不会超窗口）
  - 工具集按 AgentFull.tools 白名单过滤
  - 主代理专属工具（_MAIN_AGENT_ONLY_TOOLS）子 agent 始终不可用
"""

from __future__ import annotations

from langgraph.graph import START, StateGraph

from harness.contracts.models import AgentFull
from harness.core.foundation.state import SubAgentState
from harness.core.graph.routes import (
    build_sub_agent_route_after_agent,
    route_after_sub_agent_critic,
    route_after_sub_agent_recovery,
)

from .nodes import _build_agent_node, _build_tool_node, _recovery_node, critic_node


def build_sub_graph(agent: AgentFull, depth: int):
    """构建并编译子 agent 的轻量 StateGraph。

    每次调用均构建新图（子 agent 类型各异，工具集不同；调用频率远低于工具调用）。
    """
    allowed_names: set[str] | None = set(agent.tools) if agent.tools else None

    workflow = StateGraph(SubAgentState)
    workflow.add_node("agent", _build_agent_node(agent, depth))
    workflow.add_node("tools", _build_tool_node(allowed_names))
    workflow.add_node("recovery", _recovery_node)
    if agent.enable_critic:
        workflow.add_node("critic", critic_node)

    workflow.add_edge(START, "agent")
    workflow.add_edge("tools", "agent")
    workflow.add_conditional_edges("agent", build_sub_agent_route_after_agent(agent.enable_critic))
    workflow.add_conditional_edges("recovery", route_after_sub_agent_recovery)
    if agent.enable_critic:
        workflow.add_conditional_edges("critic", route_after_sub_agent_critic)

    return workflow.compile()
