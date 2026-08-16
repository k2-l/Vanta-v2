"""LangGraph StateGraph 定义。

拓扑：
  START → preprocess → [budget耗尽 → END]
                     → agent → [tools → agent]* → END
                             → [recovery → agent]* → END

上下文压缩（Rolling Summary）已从自动流程移除，改为用户主动触发
（见 harness/routes/sessions.py 的 compress 接口 + core/context/summarize.py）。
"""

from __future__ import annotations

from langgraph.graph import START, StateGraph

from harness.core.foundation.state import PenAgentState
from harness.core.graph.nodes import (
    agent_node,
    preprocess_node,
    recovery_node,
    tool_node,
)
from harness.core.graph.routes import (
    route_after_agent,
    route_after_preprocess,
    route_after_recovery,
)

# ─── 构建图 ───────────────────────────────────────────────────────────


def build_graph() -> StateGraph:
    workflow = StateGraph(PenAgentState)

    workflow.add_node("preprocess", preprocess_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("recovery", recovery_node)

    workflow.add_edge(START, "preprocess")
    workflow.add_edge("tools", "agent")

    workflow.add_conditional_edges("preprocess", route_after_preprocess)
    workflow.add_conditional_edges("agent", route_after_agent)
    workflow.add_conditional_edges("recovery", route_after_recovery)

    return workflow


# 编译后的单例（import 时执行，无 checkpointer 版——安全 fallback）
_default_compiled = build_graph().compile()
_compiled = _default_compiled

# 兼容旧引用：仍导出 compiled_graph（指向默认无 checkpointer 版）。
# 运行时应走 get_graph()，以拿到 lifespan 里接了 durable checkpointer 的版本。
compiled_graph = _default_compiled


def set_checkpointer(checkpointer) -> None:
    """启动时（lifespan）用 durable checkpointer 重新编译主图 —— 崩溃续跑地基。

    per-turn 唯一 thread_id（trace_id）在 runtime 传入，故各轮独立、不与 DB 重建的
    state 打架；此处只是把「每步写 checkpoint」接上。init 失败时不调用本函数，
    图退回默认版（行为不变）。
    """
    global _compiled
    _compiled = build_graph().compile(checkpointer=checkpointer)


def get_graph():
    """返回当前主图：接了 checkpointer 则为其版本，否则默认无 checkpointer 版。"""
    return _compiled
