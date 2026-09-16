"""AgentRuntime — LangGraph 引擎入口。

流程：
  用户消息 → get_graph()（preprocess→agent→tool→recovery）
           → astream_events → 映射为 Harness SSE 事件
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from weakref import WeakValueDictionary

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from harness.core.capabilities.memory import automatic_memory_available, remember
from harness.core.capabilities.services import maybe_generate_title
from harness.core.context.summarize import _extract_text
from harness.core.context.usage import _get_price_table, tracker
from harness.core.foundation.errors import _NON_RETRYABLE_ERRORS, classify_error
from harness.core.foundation.events import (
    Done,
    PhaseEvent,
    TaskLogEvent,
    TextDelta,
    ToolCall,
    ToolErrorEvent,
    ToolResultEvent,
    UsageEvent,
    WorkerEnd,
    WorkerStart,
    event_to_sse,
)
from harness.core.foundation.internal_sections import (
    InternalSectionStreamFilter,
    strip_internal_sections,
)
from harness.core.foundation.state import PenAgentState
from harness.core.foundation.tokens import (
    count_messages_tokens,
    count_tokens,
    truncate_to_tail_tokens,
)
from harness.core.graph.build import get_graph
from harness.core.graph.subagent import (
    reset_orchestration_context,
    set_parent_event_queue,
    start_orchestration_context,
)
from harness.infra import db
from harness.infra.logging import log
from harness.infra.profile import load_profile
from harness.infra.settings import get_settings
from harness.tools.registry import load_builtin_tools

# Agent 语义阶段 — 驱动子 agent / skill 的标签轮换
_AGENT_LABELS: dict[str, str] = {
    "preprocess": "准备中",
    "agent": "分析中",
    "tools": "等待结果中",
    "recovery": "错误恢复中",
}


# session 级并发锁：同一 session 同时只允许一个 graph 实例运行，防止消息乱序。
# WeakValueDictionary：Lock 对象在 session 空闲时（无协程持有引用）自动 GC，无内存泄漏。
_SESSION_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

# 全局并发门控：限制同时运行的 session 数量，防止 DB/API 被打爆。
# asyncio.Semaphore 必须在事件循环启动后创建，因此延迟初始化。
_GLOBAL_SEM: asyncio.Semaphore | None = None
_GLOBAL_SEM_LOCK: asyncio.Lock = asyncio.Lock()


def _failed_phase_events(current_agent: str, pending: set[str]) -> list[PhaseEvent]:
    """为失败运行生成所有未收尾阶段的终态事件。"""
    phase_ids = {"agent", *pending}
    if current_agent:
        phase_ids.add(f"agent:{current_agent}")
    return [
        PhaseEvent(
            id=phase_id,
            label="执行失败" if phase_id == "agent" else phase_id,
            status="failed",
        )
        for phase_id in sorted(phase_ids)
    ]


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    return lock


async def _global_sem() -> asyncio.Semaphore:
    global _GLOBAL_SEM
    if _GLOBAL_SEM is None:
        async with _GLOBAL_SEM_LOCK:
            if _GLOBAL_SEM is None:
                _GLOBAL_SEM = asyncio.Semaphore(get_settings().max_concurrent_sessions)
    return _GLOBAL_SEM


# 后台 fire-and-forget 任务的强引用集合：asyncio 不为任务保留强引用，未被引用的
# 任务可能在完成前被 GC 回收（见 asyncio.create_task 文档警告）。此处持有引用，
# 任务结束后经 done callback 自动移除，确保 best-effort 后台工作（如标题生成）跑完。
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_background(coro) -> None:
    """启动后台任务并持有其强引用，防止被 GC 提前回收。"""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _remember_best_effort(text: str, session_id: str) -> None:
    """向量记忆故障不能使已经生成的回答或 SSE 收尾失败。"""
    try:
        await asyncio.to_thread(remember, text, session_id=session_id, role="assistant")
    except Exception as exc:  # noqa: BLE001
        log.warning("memory.auto_write_failed", error=str(exc)[:200], session_id=session_id)


# 所有模式已是小写，匹配时无需 .lower()
_MEMORY_SKIP_PATTERNS = (
    "好的",
    "明白了",
    "收到",
    "好",
    "ok",
    "okay",
    "got it",
    "sure",
    "understood",
)
_MEMORY_TOKEN_LIMIT = 800
_MEMORY_TAIL_TOKENS = 300


def _filter_memory(text: str) -> str:
    """记忆写入过滤器。

    规则：
    1. 纯确认句（确认词开头 + 后面无实质内容 + 长度 < 30字） → 跳过
       若确认词后紧跟逗号/句号+实质内容，视为有效回复，不过滤（保留）
    2. 非确认词开头且文本长度 < 20 字符 → 跳过（太短，无信息量）
    3. 超过 800 token 的回复 → 只取最后 ~300 token（结论段，按换行边界对齐）
    """
    stripped = text.strip()

    # 规则 1：只对短文本（< 30字）做确认词检测，避免长文本枚举所有模式
    has_substantive_after_ack = False
    if len(stripped) < 30:
        lower = stripped.lower()
        for pat in _MEMORY_SKIP_PATTERNS:  # pat 已是小写，无需 .lower()
            if lower.startswith(pat):
                after = stripped[len(pat) :].strip()
                if not after or after in ("。", "！", "!", ".", ""):
                    return ""
                has_substantive_after_ack = True
                break

    # 规则 2：极短文本过滤（< 20 字符），但确认词后有实质内容的除外
    if len(stripped) < 20 and not has_substantive_after_ack:
        return ""

    # 规则 3：超长截断
    if count_tokens(stripped) > _MEMORY_TOKEN_LIMIT:
        return truncate_to_tail_tokens(stripped, _MEMORY_TAIL_TOKENS)
    return stripped


async def _persist_answer(
    session_id: str,
    final_text: str,
    user_message: str,
    terminal_error: str | None,
    settings,
) -> None:
    """回答落库为必需；自动记忆可用时并行写入，但不得使回答失败。"""
    tasks = [db.append_message(session_id, "assistant", final_text)]
    if automatic_memory_available(settings):
        answer = _filter_memory(final_text)
        if answer and not terminal_error and not final_text.startswith("任务已停止："):
            summary = f"Q: {user_message[:200]}\nA: {answer}"
            tasks.append(_remember_best_effort(summary, session_id))
    await asyncio.gather(*tasks)


def _validate_graph_depth(s) -> None:
    """启动时校验 graph_recursion_limit 与循环参数的一致性。

    最坏路径深度：
      preprocess(1) + agent(1) + [tools+agent] × max_tool_iterations
      + [recovery+agent] × max_recovery_attempts + summarize(1)
    """
    # 兼容测试 stub/旧运行态；正式 Settings 已拒绝非正数。
    if s.max_tool_iterations <= 0:
        log.info("graph.unbounded_tool_loop", recursion_limit=s.graph_recursion_limit)
        return
    min_required = 3 + 2 * (s.max_tool_iterations + s.max_recovery_attempts)
    safety_margin = 10
    if s.graph_recursion_limit < min_required + safety_margin:
        log.warning(
            "graph.recursion_limit_too_low",
            limit=s.graph_recursion_limit,
            min_required=min_required,
            recommended=min_required + safety_margin,
        )


class AgentRuntime:
    def __init__(self) -> None:
        load_builtin_tools()
        _validate_graph_depth(get_settings())

    async def stream_events(
        self,
        user_message: str,
        session_id: str,
        execution_env: str = "local",
    ) -> AsyncIterator[dict[str, str]]:
        """以 SSE dict 流式输出事件。供 FastAPI 路由直接消费。"""
        trace_id = uuid.uuid4().hex[:12]
        structlog.contextvars.clear_contextvars()
        # session_id 一并绑入 contextvars：既进日志，也供 run_agent 等工具从调用链
        # 读取当前会话，用于把子任务关联到会话。
        structlog.contextvars.bind_contextvars(trace=trace_id, session_id=session_id)
        s = get_settings()

        async with await _global_sem(), _session_lock(session_id):
            async for event in self._run(user_message, session_id, s, trace_id, execution_env):
                yield event

    async def _run(
        self,
        user_message: str,
        session_id: str,
        s,
        trace_id: str,
        execution_env: str = "local",
    ) -> AsyncIterator[dict[str, str]]:
        """实际执行逻辑（在 session 锁内运行）。"""
        # 1. 持久化用户消息（必须先写，才能在 step 2 正确排除最新一条）
        await db.append_message(session_id, "user", user_message)

        # 2. 并行：历史消息 + rolling_summary + profile（三路独立 I/O）
        # 历史装载走「压缩检查点」感知：有检查点则取其之后的原文（检查点之前的已在 rolling_summary
        # 里作背景注入）；无检查点（存量会话/从未主动压缩）回退「最近 N 条」，行为与旧版一致。
        history_msgs, prior_rolling_summary, profile, history_gap = await asyncio.gather(
            db.messages_after_checkpoint(session_id, fallback_n=s.history_recent_n),
            db.get_rolling_summary(session_id),
            asyncio.to_thread(load_profile),
            db.uncompacted_history_gap(session_id, fallback_n=s.history_recent_n),
        )

        history_gap_warning = ""
        if history_gap:
            history_gap_warning = (
                f"[历史覆盖提示] 当前有 {history_gap} 条更早消息未被摘要覆盖且未加载。"
                "不要猜测其内容；若当前任务依赖早期上下文，请明确建议用户先执行会话压缩。"
            )
            log.warning("history.uncompacted_gap", omitted=history_gap, trace=trace_id)

        lc_history = []
        for m in history_msgs[:-1]:  # 排除刚写入的这条
            if m.role == "user":
                lc_history.append(HumanMessage(content=m.content))
            elif m.role == "assistant":
                lc_history.append(AIMessage(content=m.content))

        # 2b. 截断超长历史 — O(n)：计算一次总量，逐条减去被删消息
        total_hist_tokens = count_messages_tokens(lc_history)
        if lc_history and total_hist_tokens > s.history_token_budget:
            while lc_history and total_hist_tokens > s.history_token_budget:
                total_hist_tokens -= count_messages_tokens([lc_history.pop(0)])
            # 确保开头是 HumanMessage（维持 human/assistant 交替）
            while lc_history and not isinstance(lc_history[0], HumanMessage):
                lc_history.pop(0)
            log.warning("history.truncated", remaining=len(lc_history), trace=trace_id)

        # 3. 构建初始状态
        initial_state: PenAgentState = {
            "messages": lc_history + [HumanMessage(content=user_message)],
            "session_id": session_id,
            "invocation_id": "agent",
            "parent_invocation_id": "",
            "agent_lineage": (),
            "invocation_tokens": 0,
            "token_limit": s.main_agent_token_limit,
            "force_finalize": False,
            "profile": profile,
            "skill_context": "",
            "recalled_memories": "",
            "rolling_summary": "\n\n".join(
                part for part in (prior_rolling_summary, history_gap_warning) if part
            ),
            "token_count": 0,
            "scratchpad": "",
            "tool_logs": [],
            "tool_iterations": 0,
            "max_tool_iterations": s.max_tool_iterations,
            "tool_failure_counts": {},
            "entity_dep_context": "",
            "error": None,
            "error_type": None,
            "recovery_attempts": 0,
            "max_recovery_attempts": s.max_recovery_attempts,
            "execution_env": execution_env,
            "trace_id": trace_id,
        }

        # 4. 运行图，监听事件流
        # 创建子 agent 事件冒泡队列，并注入 ContextVar 供子图使用
        sub_event_queue: asyncio.Queue = asyncio.Queue()
        set_parent_event_queue(sub_event_queue)
        orchestration_token = start_orchestration_context(
            s.max_agent_invocations_per_turn,
            s.agent_max_parallel,
        )

        before = tracker().get(session_id)
        before_in = before.total.input_tokens
        before_out = before.total.output_tokens
        before_by_model = {
            model: (usage.input_tokens, usage.output_tokens)
            for model, usage in before.by_model.items()
        }

        final_text = ""  # 仅保存最终无 tool_call 的 agent 轮次
        _run_streamed = ""  # 当前 agent 循环内已流式输出的文本（防重复）
        _run_filter = InternalSectionStreamFilter()
        _last_agent_label = ""  # 上一个发射的子 agent 标签（防重复）
        _current_agent = ""  # 当前活跃子 agent 名称
        _pending_sub: set[str] = set()  # 本轮待完成的子阶段 ID
        _graph_ok = True  # 图执行是否正常结束（未崩溃）
        _terminal_error: str | None = None  # TERMINAL_* 错误类型（不可重试终止）
        _tool_inputs: dict[str, dict] = {}  # tool_call_id → inputs（tools 节点结束时补发 ToolCall 卡用）
        _sub_active = False  # 子代理派发进行中：其嵌套模型事件由队列处理，主 astream 跳过防逐 token 重复
        _sub_streamed: dict[str, str] = {}  # invocation_id → 已流式公开文本
        _sub_filters: dict[str, InternalSectionStreamFilter] = {}
        def _agent_phase_id() -> str:
            """返回当前子 agent 的 phase ID（无子 agent 时用 'agent'）。"""
            return f"agent:{_current_agent}" if _current_agent else "agent"

        try:
            yield event_to_sse(
                WorkerStart(worker="agent", instruction=user_message[:80], task_id="agent")
            )
            if history_gap_warning:
                yield event_to_sse(TaskLogEvent(task_id="agent", message=history_gap_warning))
            async for event in get_graph().astream_events(
                initial_state,
                config={
                    "recursion_limit": s.graph_recursion_limit,
                    # thread_id=trace_id：per-turn 唯一，让 checkpointer 各轮独立、不与
                    # 「每轮从 DB 重建 state」打架（崩溃续跑地基，② 续跑器复用此 thread_id）。
                    "configurable": {"session_id": session_id, "thread_id": trace_id},
                },
                version="v2",
            ):
                # ── drain 子 agent 事件队列 ─────────────────────────────
                while not sub_event_queue.empty():
                    sub_ev = sub_event_queue.get_nowait()
                    agent_name = sub_ev["sub_agent"]
                    invocation_id = sub_ev.get("invocation_id") or f"sub_agent:{agent_name}"
                    inner = sub_ev["event"]
                    inner_kind = inner.get("event", "")
                    inner_data = inner.get("data", {})
                    if inner_kind == "on_tool_start":
                        tool_input = inner_data.get("input", {})
                        yield event_to_sse(
                            TaskLogEvent(
                                task_id=invocation_id,
                                message=f"[{agent_name}] → {inner.get('name', '')}({str(tool_input)[:120]})",
                            )
                        )
                        yield event_to_sse(
                            ToolCall(
                                tool=inner.get("name", ""),
                                inputs=tool_input,
                                task_id=invocation_id,
                            )
                        )
                    elif inner_kind == "on_tool_end":
                        tool_out = str(inner_data.get("output", ""))
                        ok = not tool_out.startswith(
                            ("[ERROR", "[DENIED", "[BLOCKED", "[CANCELLED", "[SKIPPED")
                        )
                        yield event_to_sse(
                            TaskLogEvent(
                                task_id=invocation_id,
                                message=f"[{agent_name}] ← {inner.get('name', '')}: {'✓' if ok else '✗'} ({len(tool_out)} 字符)",
                            )
                        )
                        # 收尾子代理工具卡：补发 ToolResult，否则卡片一直挂"运行中"
                        yield event_to_sse(
                            ToolResultEvent(
                                tool=inner.get("name", ""),
                                ok=ok,
                                output=tool_out[:2000],
                                task_id=invocation_id,
                            )
                        )
                    elif inner_kind == "on_chat_model_stream":
                        chunk = inner_data.get("chunk")
                        if chunk and hasattr(chunk, "content"):
                            text = _extract_text(chunk.content)
                            if text:
                                stream_filter = _sub_filters.setdefault(
                                    invocation_id, InternalSectionStreamFilter()
                                )
                                public_delta = stream_filter.feed(text)
                                if public_delta:
                                    _sub_streamed[invocation_id] = (
                                        _sub_streamed.get(invocation_id, "") + public_delta
                                    )
                                    yield event_to_sse(
                                        TextDelta(
                                            role="worker",
                                            text=public_delta,
                                            task_id=invocation_id,
                                        )
                                    )
                    elif inner_kind == "on_chat_model_end":
                        output = inner_data.get("output")
                        streamed = _sub_streamed.pop(invocation_id, "")
                        _sub_filters.pop(invocation_id, None)
                        if output and hasattr(output, "content"):
                            text = strip_internal_sections(_extract_text(output.content))
                            # 已流式部分不重发；只补流式未覆盖尾部（非流式模型才有）
                            if text and text != streamed:
                                remainder = text[len(streamed):] if text.startswith(streamed) else text
                                if remainder:
                                    yield event_to_sse(
                                        TextDelta(
                                            role="worker",
                                            text=remainder,
                                            task_id=invocation_id,
                                        )
                                    )
                        if output and hasattr(output, "tool_calls"):
                            for tc in output.tool_calls or []:
                                if tc.get("name") != "Agent":
                                    continue
                                entity = (tc.get("args") or {}).get("name", "")
                                child_id = f"{invocation_id}/{tc.get('id', '') or uuid.uuid4().hex[:12]}"
                                _pending_sub.add(child_id)
                                yield event_to_sse(
                                    PhaseEvent(
                                        id=child_id,
                                        label=f"{entity or '子 Agent'} 执行中",
                                        status="running",
                                        parent_id=invocation_id,
                                    )
                                )

                ev_name = event.get("event", "")
                ev_data = event.get("data", {})

                # ── Agent 语义阶段 ──────────────────────────────────────
                if ev_name == "on_chain_start":
                    node_name = event.get("name", "")
                    label = _AGENT_LABELS.get(node_name)
                    if label and label != _last_agent_label:
                        yield event_to_sse(
                            PhaseEvent(
                                id=_agent_phase_id(),
                                label=label,
                                status="running",
                            )
                        )
                        _last_agent_label = label
                    if node_name == "agent":
                        _run_streamed = ""
                        _run_filter = InternalSectionStreamFilter()

                # ── 节点结束事件 ────────────────────────────────────────
                if ev_name == "on_chain_end":
                    node_name = event.get("name", "")
                    output = ev_data.get("output", {}) or {}
                    # 捕获不可重试终止错误（AUTH_ERROR 等），稍后生成用户提示
                    if node_name == "recovery":
                        et = output.get("error_type") or ""
                        if et.startswith("TERMINAL_"):
                            _terminal_error = et
                    elif node_name == "preprocess":
                        et = output.get("error_type") or ""
                        if et.startswith("BUDGET_") and not final_text:
                            _terminal_error = f"TERMINAL_{et}"
                            budget_messages = output.get("messages", [])
                            if not isinstance(budget_messages, list):
                                budget_messages = [budget_messages]
                            for message in reversed(budget_messages):
                                if isinstance(message, AIMessage):
                                    final_text = strip_internal_sections(
                                        _extract_text(message.content)
                                    )
                                    if final_text:
                                        yield event_to_sse(
                                            TextDelta(
                                                role="worker",
                                                text=final_text,
                                                task_id="agent",
                                            )
                                        )
                                    break
                    if node_name == "tools":
                        _sub_active = False  # 子代理派发（若有）已随 tools 节点结束，恢复主流文本
                        # 工具日志逐行发射（扫描可能跨多轮，不提前结束子阶段）
                        for log_line in output.get("tool_logs", []):
                            yield event_to_sse(
                                TaskLogEvent(
                                    task_id="agent",
                                    message=log_line,
                                )
                            )
                        # 对话流按步骤分块：自定义 tool_node 不触发 on_tool_start/end，
                        # 主代理工具调用若不补发 ToolCall/ToolResult，相邻轮文本会连成一片。
                        # 编排类工具（load_agent/Skill/Agent）已作为 phase 展示，这里跳过。
                        for _tm in output.get("messages", []):
                            _tname = getattr(_tm, "name", "") or ""
                            if not _tname or _tname in ("load_agent", "Skill", "Agent"):
                                continue
                            _content = str(getattr(_tm, "content", ""))
                            _inputs = _tool_inputs.get(getattr(_tm, "tool_call_id", ""), {})
                            _ok = not _content.startswith(
                                ("[ERROR", "[DENIED", "[BLOCKED", "[CANCELLED", "[SKIPPED")
                            )
                            yield event_to_sse(ToolCall(tool=_tname, inputs=_inputs))
                            yield event_to_sse(
                                ToolResultEvent(tool=_tname, ok=_ok, output=_content[:2000])
                            )
                    elif node_name == "agent":
                        # 最终答复轮（无 tool_calls）→ 标记当前阶段完成并清空 pending 子阶段
                        last_msgs = output.get("messages", [])
                        has_tool_calls = any(
                            getattr(m, "tool_calls", None)
                            for m in (last_msgs if isinstance(last_msgs, list) else [last_msgs])
                        )
                        if not has_tool_calls:
                            # 始终发出 "已完成"，无论是否有 pending 子阶段
                            yield event_to_sse(
                                PhaseEvent(
                                    id=_agent_phase_id(),
                                    label="已完成",
                                    status="ok",
                                )
                            )
                            for sid in list(_pending_sub):
                                yield event_to_sse(
                                    PhaseEvent(
                                        id=sid,
                                        label=sid.split(":", 1)[-1],
                                        status="ok",
                                    )
                                )
                                _pending_sub.discard(sid)

                # ── LLM 完整回复 — 检测 tool_call + 发射流式未覆盖文本 ──
                if ev_name == "on_chat_model_end":
                    _was_sub = _sub_active  # 捕获进入时状态：仅主代理自身文本才发（子代理走队列）
                    output = ev_data.get("output")
                    if not _was_sub and output and hasattr(output, "tool_calls"):
                        for tc in output.tool_calls or []:
                            tc_name = tc.get("name", "")
                            args = tc.get("args", {}) or {}
                            # 记下本次工具输入，供 tools 节点结束时补发对话流的 ToolCall 卡
                            _tool_inputs[tc.get("id", "")] = args

                            # 检测 load_agent → 创建子 agent 阶段
                            if tc_name == "load_agent":
                                entity = args.get("name", "")
                                if entity:
                                    _current_agent = entity
                                    sid = f"agent:{entity}"
                                    _pending_sub.add(sid)
                                    _last_agent_label = ""
                                    yield event_to_sse(
                                        PhaseEvent(
                                            id=sid,
                                            label=f"{entity} 分析中",
                                            status="running",
                                            parent_id="agent",
                                        )
                                    )
                            # 检测 Skill → 创建子 skill 阶段
                            elif tc_name == "Skill":
                                entity = args.get("name", "")
                                if entity:
                                    sid = f"skill:{entity}"
                                    _pending_sub.add(sid)
                                    yield event_to_sse(
                                        PhaseEvent(
                                            id=sid,
                                            label=entity,
                                            status="running",
                                            parent_id=_agent_phase_id(),
                                        )
                                    )
                            # 检测 Agent → 创建子 agent 执行阶段
                            elif tc_name == "Agent":
                                entity = args.get("name", "")
                                if entity:
                                    sid = f"agent/{tc.get('id', '') or uuid.uuid4().hex[:12]}"
                                    _pending_sub.add(sid)
                                    _sub_active = True  # 之后的嵌套模型事件由队列处理，主 astream 跳过
                                    yield event_to_sse(
                                        PhaseEvent(
                                            id=sid,
                                            label=f"{entity} 执行中",
                                            status="running",
                                            parent_id=_agent_phase_id(),
                                        )
                                    )

                    # 发射流式未覆盖的文本
                    # 若已有流式累积，只补发未覆盖尾部；final_text 在确认本轮无工具调用后覆盖。
                    if not _was_sub and output and hasattr(output, "content"):
                        text = strip_internal_sections(_extract_text(output.content))
                        if text and text != _run_streamed:
                            remainder = text
                            if text.startswith(_run_streamed):
                                remainder = text[len(_run_streamed) :]
                            if remainder:
                                for line in remainder.splitlines(keepends=True):
                                    if line:
                                        yield event_to_sse(
                                            TextDelta(role="worker", text=line, task_id="agent")
                                        )
                        # 仅最终无工具调用轮次是规范 assistant 答复；中间轮只实时展示。
                        if not (output.tool_calls or []):
                            final_text = text

                # ── 流式 chunk ──────────────────────────────────────────
                elif ev_name == "on_chat_model_stream":
                    # 子代理派发中：嵌套模型 token 由队列处理，主 astream 跳过（否则逐 token 重复）
                    chunk = ev_data.get("chunk")
                    if not _sub_active and chunk and hasattr(chunk, "content"):
                        text = _extract_text(chunk.content)
                        if text:
                            public_delta = _run_filter.feed(text)
                            if public_delta:
                                _run_streamed += public_delta
                                yield event_to_sse(
                                    TextDelta(role="worker", text=public_delta, task_id="agent")
                                )

                # ── 工具调用（少量模型支持 on_tool_start/end）──────────
                elif ev_name == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_input = ev_data.get("input", {})
                    yield event_to_sse(
                        TaskLogEvent(
                            task_id="agent",
                            message=f"→ {tool_name}({str(tool_input)[:120]})",
                        )
                    )
                    yield event_to_sse(ToolCall(tool=tool_name, inputs=tool_input))

                elif ev_name == "on_tool_end":
                    tool_name = event.get("name", "")
                    output = ev_data.get("output", "")
                    output_str = str(output)
                    ok = not output_str.startswith("[ERROR")
                    yield event_to_sse(
                        TaskLogEvent(
                            task_id="agent",
                            message=f"← {tool_name}: {'✓' if ok else '✗'} ({len(output_str)} 字符)",
                        )
                    )
                    if ok:
                        yield event_to_sse(
                            ToolResultEvent(
                                tool=tool_name,
                                ok=True,
                                output=output_str[:2000],
                            )
                        )
                    else:
                        # 从 [ERROR:CODE] 格式中提取 error_code
                        code_match = re.match(r"\[ERROR:([A-Z_]+)\]", output_str)
                        error_code = (
                            code_match.group(1) if code_match else classify_error(output_str)
                        )
                        retryable = error_code not in _NON_RETRYABLE_ERRORS
                        yield event_to_sse(
                            ToolErrorEvent(
                                tool=tool_name,
                                error_code=error_code,
                                message=output_str[:500],
                                retryable=retryable,
                            )
                        )

        except GraphRecursionError:
            # 递归硬上限是最终安全网——优雅收尾而非空白 failed。
            log.warning("runtime.graph_recursion_limit", limit=s.graph_recursion_limit)
            _graph_ok = False
            if not final_text.strip():
                _rec_msg = (
                    f"任务已达图递归硬上限（graph_recursion_limit={s.graph_recursion_limit}）而停止。"
                    "这是一层安全网，通常意味着工具循环步数过多——"
                    "可在配置中调高该上限，或让我分阶段继续。"
                )
                final_text = _rec_msg
                yield event_to_sse(TextDelta(role="worker", text=_rec_msg))
        except Exception as exc:  # noqa: BLE001
            log.error("runtime.graph_error", exc=str(exc)[:300])
            _graph_ok = False
        finally:
            set_parent_event_queue(None)
            reset_orchestration_context(orchestration_token)

        # 不可重试终止时，向用户推送可读错误说明（替代空白 failed 状态）。
        if _terminal_error and not final_text.strip():
            terminal_messages: dict[str, str] = {
                "TERMINAL_AUTH_ERROR": (
                    "**API Key 认证失败**\n\n"
                    "当前配置的 API Key 无效或已过期。\n"
                    "请前往「配置」页 → 模型接口，粘贴有效的 Key 后点击应用。"
                ),
                "TERMINAL_COMMAND_NOT_FOUND": "命令或文件不存在，任务已终止。",
                "TERMINAL_PERMISSION_DENIED": "权限不足，任务已终止。",
                "TERMINAL_BUDGET_SESSION": "本次会话的全局 token 硬限额已耗尽，任务已终止。",
                "TERMINAL_BUDGET_DAILY": "今日全局 token 硬限额已耗尽，任务已终止。",
            }
            err_msg = terminal_messages.get(
                _terminal_error,
                f"任务因不可恢复错误终止（{_terminal_error}）。",
            )
            final_text = err_msg
            yield event_to_sse(TextDelta(role="worker", text=err_msg, task_id="agent"))

        # 5. 持久化 + 记忆（并行）+ 标题（fire-and-forget）
        if final_text.strip():
            await _persist_answer(session_id, final_text, user_message, _terminal_error, s)

            async def _gen_title() -> None:
                try:
                    await maybe_generate_title(session_id)
                except Exception as _exc:  # noqa: BLE001
                    log.warning("title_generation.failed", exc=str(_exc)[:100])

            _spawn_background(_gen_title())

        _status = (
            "ok" if _graph_ok and not _terminal_error and final_text.strip() else "failed"
        )
        if _status == "failed":
            for phase_event in _failed_phase_events(_current_agent, _pending_sub):
                yield event_to_sse(phase_event)
            _pending_sub.clear()
        yield event_to_sse(
            WorkerEnd(worker="agent", status=_status, summary=final_text[:100], task_id="agent")
        )

        # 6. 用量事件
        after = tracker().get(session_id)
        turn_in = after.total.input_tokens - before_in
        turn_out = after.total.output_tokens - before_out
        price_table = _get_price_table()
        turn_cost = 0.0
        turn_models: list[str] = []
        for model, usage in after.by_model.items():
            old_in, old_out = before_by_model.get(model, (0, 0))
            delta_in = usage.input_tokens - old_in
            delta_out = usage.output_tokens - old_out
            if delta_in or delta_out:
                turn_models.append(model)
                prices = price_table.get(model)
                if prices:
                    turn_cost += (delta_in * prices[0] + delta_out * prices[1]) / 1_000_000
        yield event_to_sse(
            UsageEvent(
                model=(
                    turn_models[0]
                    if len(turn_models) == 1
                    else ("mixed" if turn_models else s.model_mid)
                ),
                turn_input=turn_in,
                turn_output=turn_out,
                turn_cost_usd=round(turn_cost, 4),
                session_input=after.total.input_tokens,
                session_output=after.total.output_tokens,
                session_cost_usd=round(after.cost_usd(), 4),
            )
        )

        yield event_to_sse(Done())
