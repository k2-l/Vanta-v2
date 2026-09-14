"""context — 子 agent 执行的 ContextVar 上下文（叶子模块，仅依赖 stdlib）。

承载两个 asyncio-safe ContextVar：
  - _agent_depth：子 agent 递归深度，供 RunAgentTool 做深度上限检查。
  - _parent_event_queue：父流事件注入队列，子 agent 向其 put 事件冒泡到主流。

两者均通过本模块的公共访问器读写，外部代码不直接操作私有 ContextVar。
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# ── 调用深度追踪（asyncio-safe ContextVar）──────────────────────────────
# run_agent 工具读取此值决定是否允许继续派发；
# 每次进入子 agent 时递增，退出后自动还原（ContextVar.reset）。
_agent_depth: contextvars.ContextVar[int] = contextvars.ContextVar("harness_agent_depth", default=0)


@dataclass
class OrchestrationContext:
    """一次根任务共享的编排护栏；token 预算不放在这里，保持 invocation 隔离。"""

    max_invocations: int
    max_parallel: int
    total_invocations: int = 0
    active_direct_by_parent: dict[str, int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.semaphore = asyncio.Semaphore(self.max_parallel)


_orchestration: contextvars.ContextVar[OrchestrationContext | None] = contextvars.ContextVar(
    "harness_orchestration", default=None
)
_invocation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "harness_agent_invocation_id", default="agent"
)
_agent_lineage: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "harness_agent_lineage", default=()
)
_tool_call_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "harness_tool_call_id", default=""
)


def current_sub_agent_depth() -> int:
    """当前子 agent 递归深度（0 = 主代理）。供 RunAgentTool 做深度上限检查。"""
    return _agent_depth.get()


def current_invocation_id() -> str:
    return _invocation_id.get()


def current_agent_lineage() -> tuple[str, ...]:
    return _agent_lineage.get()


def current_tool_call_id() -> str:
    return _tool_call_id.get()


def start_orchestration_context(max_invocations: int, max_parallel: int) -> contextvars.Token:
    """为根任务创建共享的次数/并发护栏，返回可用于 reset 的 token。"""
    return _orchestration.set(
        OrchestrationContext(
            max_invocations=max(1, max_invocations),
            max_parallel=max(1, max_parallel),
        )
    )


def reset_orchestration_context(token: contextvars.Token) -> None:
    _orchestration.reset(token)


def get_orchestration_context() -> OrchestrationContext | None:
    return _orchestration.get()


async def reserve_delegation(parent_id: str, direct_limit: int) -> str | None:
    """原子预留一个活跃直接子调用；总 invocation 数仍按整回合累计。"""
    ctx = _orchestration.get()
    if ctx is None:
        # 非标准入口（例如直接单测工具）也要有护栏，但不与其它根任务共享。
        ctx = OrchestrationContext(max_invocations=max(1, direct_limit), max_parallel=1)
        _orchestration.set(ctx)
    async with ctx.lock:
        direct = ctx.active_direct_by_parent.get(parent_id, 0)
        if direct >= max(1, direct_limit):
            return "DELEGATION_LIMIT"
        if ctx.total_invocations >= ctx.max_invocations:
            return "AGENT_INVOCATION_LIMIT"
        ctx.active_direct_by_parent[parent_id] = direct + 1
        ctx.total_invocations += 1
    return None


async def release_delegation(parent_id: str) -> None:
    """释放父 invocation 的一个活跃直接子调用槽；不回退全局累计次数。"""
    ctx = _orchestration.get()
    if ctx is None:
        return
    async with ctx.lock:
        active = ctx.active_direct_by_parent.get(parent_id, 0)
        if active <= 1:
            ctx.active_direct_by_parent.pop(parent_id, None)
        else:
            ctx.active_direct_by_parent[parent_id] = active - 1


def child_invocation_id(parent_id: str) -> str:
    call_id = _tool_call_id.get() or uuid.uuid4().hex[:12]
    return f"{parent_id}/{call_id}"


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


@contextmanager
def enter_agent_invocation(invocation_id: str, agent_name: str) -> Iterator[None]:
    """切换当前 invocation/lineage；子任务自动继承同一个编排上下文。"""
    invocation_token = _invocation_id.set(invocation_id)
    lineage_token = _agent_lineage.set((*_agent_lineage.get(), agent_name))
    try:
        yield
    finally:
        _agent_lineage.reset(lineage_token)
        _invocation_id.reset(invocation_token)


@contextmanager
def bind_tool_call_id(call_id: str) -> Iterator[None]:
    token = _tool_call_id.set(call_id or "")
    try:
        yield
    finally:
        _tool_call_id.reset(token)


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
