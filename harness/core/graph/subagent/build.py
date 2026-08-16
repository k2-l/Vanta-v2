"""build — 子 agent 轻量 StateGraph 的组装。

拓扑：
  START → agent → [tools → agent]* → END
                ↘ recovery → agent* → END
<<<<<<< HEAD
                ↘ [enable_critic=True] critic → [FAIL,attempts<2] agent
                                               → [PASS|attempts>=2] END
=======
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

与主代理图的区别：
  - 无 preprocess（子 agent 不加载记忆/画像/skill 上下文）
  - 无 summarize（子 agent 任务有界，不会超窗口）
<<<<<<< HEAD
  - 工具集按 AgentContent.tools 白名单过滤
=======
  - 工具集按 AgentFull.tools 白名单过滤
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
  - 主代理专属工具（_MAIN_AGENT_ONLY_TOOLS）子 agent 始终不可用
"""

from __future__ import annotations

from langgraph.graph import START, StateGraph

<<<<<<< HEAD
from harness.agents.loader import AgentContent
from harness.core.foundation.state import SubAgentState
from harness.core.graph.routes import (
    build_sub_agent_route_after_agent,
    route_after_sub_agent_critic,
    route_after_sub_agent_recovery,
)

from .nodes import _build_agent_node, _build_tool_node, _recovery_node, critic_node


def build_sub_graph(agent: AgentContent, depth: int):
    """构建并编译子 agent 的轻量 StateGraph。

    每次调用均构建新图（子 agent 类型各异，工具集不同；调用频率远低于工具调用）。
    enable_critic=True 时额外注册 critic 节点，对无 tool_call 的最终回复做质量校验
    （FAIL 且重试次数<2 时回到 agent 重试，最多 2 次后放行）。
=======
from harness.contracts.models import AgentFull
from harness.core.foundation.state import SubAgentState
from harness.core.graph.routes import (
    build_sub_agent_route_after_agent,
    route_after_sub_agent_recovery,
)

from .nodes import _build_agent_node, _build_tool_node, _recovery_node


def build_sub_graph(agent: AgentFull, depth: int):
    """构建并编译子 agent 的轻量 StateGraph。

    每次调用均构建新图（子 agent 类型各异，工具集不同；调用频率远低于工具调用）。
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    """
    allowed_names: set[str] | None = set(agent.tools) if agent.tools else None

    workflow = StateGraph(SubAgentState)
    workflow.add_node("agent", _build_agent_node(agent, depth))
    workflow.add_node("tools", _build_tool_node(allowed_names))
    workflow.add_node("recovery", _recovery_node)

    workflow.add_edge(START, "agent")
    workflow.add_edge("tools", "agent")
<<<<<<< HEAD
    workflow.add_conditional_edges("agent", build_sub_agent_route_after_agent(agent.enable_critic))
    workflow.add_conditional_edges("recovery", route_after_sub_agent_recovery)

    if agent.enable_critic:
        workflow.add_node("critic", critic_node)
        workflow.add_conditional_edges("critic", route_after_sub_agent_critic)

=======
    workflow.add_conditional_edges("agent", build_sub_agent_route_after_agent(False))
    workflow.add_conditional_edges("recovery", route_after_sub_agent_recovery)

>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    return workflow.compile()
