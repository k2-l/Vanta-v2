"""Tool execution node for the main LangGraph agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from harness.core.context.summarize import _compress_context
from harness.core.foundation.errors import classify_error, most_severe_error_type
from harness.core.foundation.registry import LRUDict
from harness.core.foundation.state import PenAgentState
from harness.core.graph.tool_exec import (
    collect_tool_results,
    disclosed_from_tool_calls,
    execute_tool_core,
    skipped_tool_messages,
)
from harness.infra.logging import log
from harness.infra.metrics import inc as _inc
from harness.infra.settings import get_settings
from harness.tools.exec_context import apply_engagement, apply_exec_env

CACHEABLE_TOOLS: frozenset[str] = frozenset({"knowledge"})
_TOOL_CACHE_TTL = 120.0  # seconds
_MAX_CACHE_SESSIONS = 200
_MAX_CACHE_ENTRIES_PER_SESSION = 50
# session_id -> {cache_key -> (content: str, ts: float)}  — LRU 双层有界缓存
_tool_cache: LRUDict = LRUDict(maxsize=_MAX_CACHE_SESSIONS)


def _get_session_cache(session_id: str) -> OrderedDict[str, tuple[str, float]]:
    """返回该 session 的缓存字典，必要时创建；LRU 淘汰由 LRUDict.__setitem__ 自动处理。"""
    if session_id in _tool_cache:
        _tool_cache.move_to_end(session_id)  # 读访问时标记为最近访问
    else:
        _tool_cache[session_id] = OrderedDict()  # LRUDict 自动淘汰最久未访问的 session
    return _tool_cache[session_id]


async def _execute_tool_call(
    tc: dict,
    *,
    _s,
    session_id: str,
    sem: asyncio.Semaphore,
    failure_counts: dict[str, int],
    trace_id: str,
) -> tuple[ToolMessage, list[str], str | None]:
    """Execute a single tool call. Returns (ToolMessage, logs, error_str)."""
    tool_name = tc.get("name", "")
    tool_input = tc.get("args", {})
    call_id = tc.get("id", "")
    local_logs: list[str] = [f"→ {tool_name}({str(tool_input)[:120]})"]

    # Agent(旧名 run_agent) context 压缩（策略外壳，保留）
    if tool_name in ("Agent", "run_agent"):
        _ctx = (
            tool_input.get("context")
            if isinstance(tool_input, dict)
            else getattr(tool_input, "args", {}).get("context")
        )
        if _ctx and len(_ctx) > _s.context_summary_target_chars:
            _compressed = await _compress_context(
                _ctx,
                target_chars=_s.context_summary_target_chars,
                model_name=_s.model_low,
                api_key=_s.anthropic_api_key or None,
                base_url=_s.anthropic_base_url or None,
            )
            if isinstance(tool_input, dict):
                tool_input = {**tool_input, "context": _compressed}
            else:
                tool_input = {**tool_input.args, "context": _compressed}

    # 缓存命中早返回（策略外壳，保留）
    cache_key = None
    if tool_name in CACHEABLE_TOOLS:
        raw = json.dumps({"tool": tool_name, "args": tool_input}, sort_keys=True, default=str)
        cache_key = hashlib.md5(raw.encode()).hexdigest()
        scache = _get_session_cache(session_id)
        cached = scache.get(cache_key)
        if cached is not None:
            cached_content, cached_ts = cached
            if time.monotonic() - cached_ts < _TOOL_CACHE_TTL:
                scache.move_to_end(cache_key)
                local_logs.append(f"[CACHED] ← {tool_name}: ✓ ({len(cached_content)} 字符)")
                _inc("tool.cache.hit")
                return (
                    ToolMessage(
                        content=cached_content,
                        tool_call_id=call_id,
                        name=tool_name,
                        additional_kwargs={"cached": True},
                    ),
                    local_logs,
                    None,
                )

    # 委托共享内核（主图现在也带 per-tool 超时）
    content, error_code, error_str, flags, core_logs = await execute_tool_core(
        tool_name,
        tool_input,
        sem=sem,
        timeout=_s.tool_timeout_seconds,
        max_output_chars=_s.max_tool_output_chars,
        log_event="tool.exec",
        metric_prefix="tool.exec",
        trace_id=trace_id,
        session_id=session_id,
    )
    local_logs.extend(core_logs)

    # 成功则写缓存（策略外壳，保留）
    if error_code is None and cache_key is not None:
        scache = _get_session_cache(session_id)
        scache[cache_key] = (content, time.monotonic())
        scache.move_to_end(cache_key)
        while len(scache) > _MAX_CACHE_ENTRIES_PER_SESSION:
            scache.popitem(last=False)

    # 失败计数 + 提示注入（策略外壳，保留）
    if error_str is not None:
        new_count = failure_counts.get(tool_name, 0) + 1
        if error_code == "COMMAND_NOT_FOUND":
            content += "\n[提示] 该工具未注册，请询问用户是否需要安装或启用该工具。"
        elif new_count >= _s.tool_failure_max_retries:
            content += (
                f"\n[提示] 工具 {tool_name!r} 已累计失败 {new_count} 次（上限 {_s.tool_failure_max_retries}），"
                "请改用其他工具替代，不要继续重试该工具。"
            )

    return (
        ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=tool_name,
            additional_kwargs={
                **({} if not error_code else {"error_code": error_code}),
                **({} if not flags else {"injection_flags": flags}),
            },
        ),
        local_logs,
        error_str,
    )


# ─── 节点 3：tool ────────────────────────────────────────────────────


async def _apply_active_engagement(session_id: str) -> None:
    """把会话的活跃 engagement（scope）叠加到 ExecEnv，供工具/沙箱读取当前授权范围。

    fail-safe：session 无 / 无活跃 engagement / 加载失败 → 清为"无 engagement"（主动扫描
    类动作因此被拒，宁紧勿松）。仅 PK 查询，开销小。
    """
    if not session_id:
        apply_engagement("", session_id="")
        return
    try:
        from harness.infra.db import get_active_engagement_id, get_engagement

        eid = await get_active_engagement_id(session_id)
        eng = await get_engagement(eid) if eid else None
        if eng is None:
            apply_engagement("", session_id=session_id)
            return
        apply_engagement(
            eng.id, tuple(eng.scope_targets or ()), eng.dns_resolver_ip or "", session_id=session_id
        )
    except Exception as exc:  # noqa: BLE001 —— 加载失败 fail-safe 到"无 engagement"，不阻断执行
        log.warning("tool_node.engagement_load_failed", session_id=session_id, exc=str(exc)[:200])
        apply_engagement("", session_id=session_id)


async def tool_node(state: PenAgentState, config: RunnableConfig) -> dict:
    """执行最后一条 AI 消息中的所有 tool_call，并发运行。"""
    messages = state.get("messages", [])
    if not messages:
        return {}

    last = messages[-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {}

    _s = get_settings()

    # Propagate execution environment to tools via ContextVar
    apply_exec_env(state.get("execution_env"))
    # 叠加会话的活跃 engagement（scope 门来源）——在 create_task 前设好，任务复制到该上下文
    await _apply_active_engagement(state.get("session_id", ""))

    max_tc = _s.max_tool_calls_per_turn  # <=0 不限本轮工具数（仍受 tool_concurrency 约束）
    tool_calls = last.tool_calls[:max_tc] if max_tc > 0 else last.tool_calls
    if max_tc > 0 and len(last.tool_calls) > max_tc:
        log.warning("tool_node.truncated", total=len(last.tool_calls), limit=max_tc)

    sem = asyncio.Semaphore(_s.tool_concurrency)

    session_id = state.get("session_id", "")

    _failure_counts_in_state: dict[str, int] = dict(state.get("tool_failure_counts") or {})

    try:
        tasks: list[asyncio.Task] = [
            asyncio.create_task(
                _execute_tool_call(
                    tc,
                    _s=_s,
                    session_id=session_id,
                    sem=sem,
                    failure_counts=_failure_counts_in_state,
                    trace_id=state.get("trace_id", ""),
                )
            )
            for tc in tool_calls
        ]

        raw = await asyncio.gather(*tasks, return_exceptions=True)

        tool_messages, ordered_logs, errors, failed = collect_tool_results(tool_calls, raw)
        # 悬空 tool_use 守卫：给被 max_tc 截断、未执行的 tool_call 补合成结果，
        # 使 AIMessage 里每个 tool_use 都有配对 tool_result，避免下一轮 Anthropic 调用 400。
        if max_tc > 0 and len(last.tool_calls) > max_tc:
            tool_messages = tool_messages + skipped_tool_messages(last.tool_calls[max_tc:])
        new_failure_counts = dict(_failure_counts_in_state)
        for name in failed:
            new_failure_counts[name] = new_failure_counts.get(name, 0) + 1

        update: dict[str, Any] = {
            "messages": tool_messages,
            "tool_logs": ordered_logs,
            "tool_iterations": state.get("tool_iterations", 0) + 1,
            "tool_failure_counts": new_failure_counts,
        }
        # tool_search 命中的 dynamic 工具名写回 disclosed_tools（reducer 去重累积），
        # 下一轮 agent_node rebind 时即可绑定、模型可真正调用。
        disclosed = disclosed_from_tool_calls(tool_calls)
        if disclosed:
            update["disclosed_tools"] = disclosed
            log.info("tool_node.disclosed", tools=disclosed)
        if errors:
            update["error"] = "; ".join(errors)
            update["error_type"] = most_severe_error_type(errors)
        return update

    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        log.error("tool_node.crash", exc=err[:300])
        return {
            "error": err,
            "error_type": classify_error(err),
        }
