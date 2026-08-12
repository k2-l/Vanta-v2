"""subagent — 子 agent 轻量执行图（替代旧 subgraph.py）。

模块划分（导入 DAG 无环：context ← nodes ← build ← runtime ← __init__）：
  - context.py  ：调用深度 + 父流事件队列 ContextVar 及访问器（叶子）
  - nodes.py    ：agent/tool/recovery 节点工厂 + critic 节点
  - build.py    ：build_sub_graph 图组装
  - runtime.py  ：run_sub_agent 公共执行入口

仅 re-export 公共面；内部实现请直接 from harness.core.graph.subagent.<module> import。
"""

from __future__ import annotations

from .context import (
    current_sub_agent_depth as current_sub_agent_depth,
)
from .context import (
    enter_sub_agent_depth as enter_sub_agent_depth,
)
from .context import (
    set_parent_event_queue as set_parent_event_queue,
)
from .runtime import run_sub_agent as run_sub_agent

__all__ = [
    "current_sub_agent_depth",
    "enter_sub_agent_depth",
    "run_sub_agent",
    "set_parent_event_queue",
]
