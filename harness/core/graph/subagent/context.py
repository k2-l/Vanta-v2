"""context — 子 agent 执行的 ContextVar 上下文（叶子模块，仅依赖 stdlib）。

承载两个 asyncio-safe ContextVar：
  - _agent_depth：子 agent 递归深度，供 RunAgentTool 做深度上限检查。
  - _parent_event_queue：父流事件注入队列，子 agent 向其 put 事件冒泡到主流。

两者均通过本模块的公共访问器读写，外部代码不直接操作私有 ContextVar。
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

# ── 调用深度追踪（asyncio-safe ContextVar）──────────────────────────────
# run_agent 工具读取此值决定是否允许继续派发；
# 每次进入子 agent 时递增，退出后自动还原（ContextVar.reset）。
_agent_depth: contextvars.ContextVar[int] = contextvars.ContextVar("harness_agent_depth", default=0)


def current_sub_agent_depth() -> int:
    """当前子 agent 递归深度（0 = 主代理）。供 RunAgentTool 做深度上限检查。"""
    return _agent_depth.get()


@contextmanager
def enter_sub_agent_depth() -> Iterator[int]:
    """进入一层子 agent 递归：yield 新深度，退出时自动还原。

    封装 _agent_depth 的 set/reset，使工具层不必直接操作私有 ContextVar。
    """
    new_depth = _agent_depth.get() + 1
    token = _agent_depth.set(new_depth)
    try:
        yield new_depth
    finally:
        _agent_depth.reset(token)


# ── 父流事件注入队列 ────────────────────────────────────────────────────
# 主代理运行时设置，子 agent 向其 put 事件。外部通过下方访问器读写，不直接 reach 进 ContextVar。
_parent_event_queue: contextvars.ContextVar[asyncio.Queue | None] = contextvars.ContextVar(
    "harness_parent_event_queue", default=None
)


def set_parent_event_queue(queue: asyncio.Queue | None) -> None:
    """设置父流事件队列（主代理 runtime._run 在会话开始时调用）。"""
    _parent_event_queue.set(queue)


def get_parent_event_queue() -> asyncio.Queue | None:
    """读取父流事件队列（子 agent runtime 在转发事件前调用；未设置时为 None）。"""
    return _parent_event_queue.get()
