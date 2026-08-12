"""runtime — 子 agent 的公共执行入口 run_sub_agent。

构建并流式运行子 agent 图，把关键事件冒泡到父流（经 _parent_event_queue），
最终返回子 agent 的文本输出。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from harness.agents.loader import AgentContent
from harness.core.context.summarize import _extract_text
from harness.core.foundation.state import SubAgentState
from harness.infra.settings import get_settings
from harness.tools.exec_context import get_exec_env

from .build import build_sub_graph
from .context import get_parent_event_queue


async def run_sub_agent(
    *,
    agent: AgentContent,
    task: str,
    context: str,
    depth: int,
    session_id: str,
    trace_id: str,
) -> str:
    """执行子 agent，返回最终文本输出。

    在调用前需设置 _agent_depth（由 RunAgentTool 负责），
    此函数本身不再修改 ContextVar，避免双重递增。
    """
    s = get_settings()
    if depth > s.sub_agent_max_depth:
        raise RuntimeError(
            f"已达到最大调用深度 (depth={depth}，上限={s.sub_agent_max_depth})，拒绝继续派发"
        )
    compiled = build_sub_graph(agent, depth)

    # 继承父 agent 的执行环境
    env = get_exec_env()
    exec_env_str = f"container:{env.container_id}" if env.is_container else "local"

    # 把上下文拼入任务描述（让子 agent 直接看到前置结果）
    user_content = task
    if context:
        user_content = f"{task}\n\n## 上下文（来自上游 agent）\n{context}"

    initial_state: SubAgentState = {
        "messages": [HumanMessage(content=user_content)],
        "session_id": session_id,
        "agent_name": agent.name,
        "agent_depth": depth,
        "tool_logs": [],
        "tool_iterations": 0,
        "max_tool_iterations": s.sub_agent_max_tool_iterations,
        "error": None,
        "error_type": None,
        "recovery_attempts": 0,
        "max_recovery_attempts": s.sub_agent_max_recovery_attempts,
        "execution_env": exec_env_str,
        "trace_id": trace_id,
    }

    queue = get_parent_event_queue()

    # 用 astream_events 替换 ainvoke，把关键子 agent 事件转发给父流
    final_messages: list = []
    async for ev in compiled.astream_events(
        initial_state,
        config={"recursion_limit": s.sub_agent_recursion_limit},
        version="v2",
    ):
        # 转发关键事件到父队列（供 runtime._run 消费并发射 SSE）
        # critic 是内部质检节点，其模型输出不进对话流：按 langgraph_node 过滤掉。
        if queue is not None:
            kind = ev.get("event", "")
            node = ev.get("metadata", {}).get("langgraph_node", "")
            if node != "critic" and kind in (
                "on_chat_model_stream",
                "on_chat_model_end",
                "on_tool_start",
                "on_tool_end",
            ):
                await queue.put({"sub_agent": agent.name, "event": ev})

        # 从 LangGraph on_chain_end 事件捕获最终状态
        if ev.get("event") == "on_chain_end" and ev.get("name") == "LangGraph":
            output = ev.get("data", {}).get("output", {})
            msgs = output.get("messages", [])
            if msgs:
                final_messages = msgs

    # 提取最后一条 AI 消息作为结果
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            text = _extract_text(msg.content)
            if text:
                return text
    return "[子 agent 未产生文本输出]"
