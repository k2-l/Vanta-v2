"""nodes — 子 agent 图的节点工厂与 critic 节点。

包含：
  - _MAIN_AGENT_ONLY_TOOLS：主代理专属工具集（子 agent 永不可用）
  - _build_agent_node：绑定特定 agent 配置的 agent_node 工厂
  - _execute_subgraph_tool_call / _build_tool_node：白名单工具执行（安全防线）
  - _recovery_node：子 agent 精简版错误恢复
  - critic_node：可选回复质量门（enable_critic=True 时由 build_sub_graph 注册）
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

<<<<<<< HEAD
from harness.agents.loader import AgentContent
=======
from harness.contracts.models import AgentFull
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
from harness.core.context.budget import record_usage
from harness.core.context.summarize import _extract_text
from harness.core.foundation.errors import (
    _BACKOFF_SECONDS,
    _NON_RETRYABLE_ERRORS,
    _RECOVERY_PROMPTS,
    classify_error,
    most_severe_error_type,
)
from harness.core.foundation.state import SubAgentState
from harness.core.foundation.tokens import count_tokens
from harness.core.graph.models import _get_base_model
from harness.core.graph.tool_exec import (
    collect_tool_results,
    disclosed_from_tool_calls,
    execute_tool_core,
    skipped_tool_messages,
)
from harness.infra.logging import log
from harness.infra.metrics import inc as _inc
from harness.infra.settings import get_settings
from harness.tools.exec_context import apply_exec_env
from harness.tools.registry import registry

from .context import _agent_depth

# 只有主代理才能使用的工具，子 agent 无论白名单如何配置均不可用
_MAIN_AGENT_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "Agent",
    }
)


# ─── 子 agent 节点：agent ─────────────────────────────────────────────


_SUB_TOOL_SEARCH_HINT = (
    "\n\n# 动态工具（tool_search）\n"
    "部分专用工具（CLI / MCP）未直接列出，需要时先用 `tool_search` 按关键词搜索；"
    "命中的工具会在下一轮解锁并附完整参数定义后才能调用。未见其 schema 前禁止臆测参数直接调用。"
)


<<<<<<< HEAD
def _build_agent_node(agent: AgentContent, depth: int):
=======
def _build_agent_node(agent: AgentFull, depth: int):
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    """返回绑定了特定 agent 配置的 agent_node。

    depth：当前子 agent 所处深度（1 或 2）。
    工具绑定分两种：
      - 白名单**非空** → 显式选择优先，构建时一次性绑定指定工具（不参与 tool_search）。
      - 白名单**为空** → 绑定 static 集 + 已披露 dynamic + tool_search，并在闭包内按
        state["disclosed_tools"] 逐轮 rebind（带 per-closure 小缓存），使披露即时生效。
    两种情况都始终排除主代理专属工具（_MAIN_AGENT_ONLY_TOOLS）。
    """
    s = get_settings()
    model_name = agent.model or s.model_mid

    base_model = _get_base_model(
        model_name,
        s.anthropic_api_key,
        s.anthropic_base_url,
<<<<<<< HEAD
        agent.max_tokens,
=======
        s.max_tokens_per_turn,
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    )

    allowed_names = set(agent.tools) if agent.tools else None
    # 白名单模式：显式选择，构建时定死一份绑定（含用户点名的 dynamic 工具，get 按名取不受 disclosure 影响）。
    if allowed_names:
        static_tools = [
            t.to_langchain()
            for t in registry.list(list(allowed_names))
            if t.name not in _MAIN_AGENT_ONLY_TOOLS
        ]
        fixed_bound = base_model.bind_tools(static_tools) if static_tools else base_model
    else:
        # 全量模式：static 常驻集 + tool_search（常驻），dynamic 部分按披露逐轮追加。
        fixed_bound = None
        static_tools = [
            t for t in registry.lc_tools_static() if t["name"] not in _MAIN_AGENT_ONLY_TOOLS
        ]

    # 全量模式下按 disclosed 元组缓存绑定，避免每轮 bind_tools 重建。
    _bound_by_disclosed: dict[tuple[str, ...], Any] = {}

    def _bind_for(disclosed: list[str]):
        if fixed_bound is not None:
            return fixed_bound
        key = tuple(sorted(disclosed))
        if key not in _bound_by_disclosed:
            extra = [
                d
                for d in registry.get_langchain(disclosed)
                if d["name"] not in _MAIN_AGENT_ONLY_TOOLS
            ]
            lc = static_tools + extra
            _bound_by_disclosed[key] = base_model.bind_tools(lc) if lc else base_model
            if len(_bound_by_disclosed) > 16:
                del _bound_by_disclosed[next(iter(_bound_by_disclosed))]
        return _bound_by_disclosed[key]

    async def agent_node(state: SubAgentState, config: RunnableConfig) -> dict:
<<<<<<< HEAD
        content = agent.content or f"你是{agent.name}，专业 AI 助手。"
=======
        content = agent.content or f"你是{agent.meta.name}，专业 AI 助手。"
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
        # 全量模式且存在可披露 dynamic 工具时，追加 tool_search 使用说明。
        if fixed_bound is None and registry.dynamic_specs():
            content = content + _SUB_TOOL_SEARCH_HINT
        system_msg = SystemMessage(content=content)
        messages = [system_msg] + list(state.get("messages", []))
        bound = _bind_for(state.get("disclosed_tools") or [])
        try:
            response = await bound.ainvoke(messages, config=config)
            usage = getattr(response, "response_metadata", {}).get("usage", {})
            in_t = usage.get("input_tokens", count_tokens(agent.content or ""))
            out_t = usage.get(
                "output_tokens",
                count_tokens(
                    response.content if isinstance(response.content, str) else str(response.content)
                ),
            )
            await record_usage(state.get("session_id", "_anon"), model_name, in_t, out_t)
            log.info(
                "sub_agent.llm_ok",
<<<<<<< HEAD
                agent=agent.name,
=======
                agent=agent.meta.name,
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
                tool_calls=len(response.tool_calls or []),
                in_t=in_t,
                out_t=out_t,
                depth=depth,
            )
            _inc("sub_agent.llm_calls")
            return {"messages": [response], "error": None, "error_type": None}
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
<<<<<<< HEAD
            log.warning("sub_agent.llm_error", agent=agent.name, exc=err[:200])
=======
            log.warning("sub_agent.llm_error", agent=agent.meta.name, exc=err[:200])
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
            _inc("sub_agent.llm_errors")
            return {"error": err, "error_type": classify_error(err)}

    return agent_node


# ─── 子 agent 节点：tool ──────────────────────────────────────────────


async def _execute_subgraph_tool_call(
    tc: dict,
    *,
    allowed_names: set[str] | None,
    sem: asyncio.Semaphore,
    s,
    session_id: str,
) -> tuple[ToolMessage, list[str], str | None]:
    """Execute a single tool call inside a sub-agent tool_node. Returns (ToolMessage, logs, error_str|None)."""
    tool_name = tc.get("name", "")
    tool_input = tc.get("args", {})
    call_id = tc.get("id", "")
    local_logs: list[str] = [f"→ {tool_name}({str(tool_input)[:120]})"]

    # 主代理专属工具拦截（策略外壳，保留）
    if tool_name in _MAIN_AGENT_ONLY_TOOLS:
        content = f"[ERROR:PERMISSION_DENIED] {tool_name!r} 是主代理专属工具，子 agent 无权调用"
        local_logs.append(f"← {tool_name}: ✗ (主代理专属)")
        return (
            ToolMessage(
                content=content,
                tool_call_id=call_id,
                name=tool_name,
                additional_kwargs={"error_code": "PERMISSION_DENIED"},
            ),
            local_logs,
            content,
        )

    # 白名单检查（策略外壳，保留）
    if allowed_names is not None and tool_name not in allowed_names:
        content = f"[ERROR:PERMISSION_DENIED] 子 agent 无权调用工具 {tool_name!r}"
        local_logs.append(f"← {tool_name}: ✗ (权限拒绝)")
        return (
            ToolMessage(
                content=content,
                tool_call_id=call_id,
                name=tool_name,
                additional_kwargs={"error_code": "PERMISSION_DENIED"},
            ),
            local_logs,
            content,
        )

    # 委托共享内核
    content, error_code, error_str, _flags, core_logs = await execute_tool_core(
        tool_name,
        tool_input,
        sem=sem,
        timeout=s.tool_timeout_seconds,
        max_output_chars=s.max_tool_output_chars,
        log_event="sub_agent.tool.exec",
        metric_prefix="sub_agent.tool",
        session_id=session_id,
    )
    local_logs.extend(core_logs)
    return (
        ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=tool_name,
            additional_kwargs={} if not error_code else {"error_code": error_code},
        ),
        local_logs,
        error_str,
    )


def _build_tool_node(allowed_names: set[str] | None):
    """返回只执行白名单内工具的 tool_node（安全防线）。

    白名单为 None 时执行全量工具；子 agent 的 tool_node 使用精确白名单。
    """
    s = get_settings()

    async def tool_node(state: SubAgentState, config: RunnableConfig) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {}
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {}

        apply_exec_env(state.get("execution_env"))

        # 从 state 同步深度到 ContextVar，确保嵌套 run_agent 调用读取正确深度
        current_depth = state.get("agent_depth", 0)
        depth_token = _agent_depth.set(current_depth)

        tool_calls = last.tool_calls[: s.max_tool_calls_per_turn]
        sem = asyncio.Semaphore(s.tool_concurrency)
        sid = state.get("session_id", "_anon")

        try:
            raw = await asyncio.gather(
                *[
                    _execute_subgraph_tool_call(
                        tc, allowed_names=allowed_names, sem=sem, s=s, session_id=sid
                    )
                    for tc in tool_calls
                ],
                return_exceptions=True,
            )
        finally:
            _agent_depth.reset(depth_token)

        tool_messages, ordered_logs, errors, _failed = collect_tool_results(tool_calls, raw)
        # 悬空 tool_use 守卫（同主图）：截断掉的 tool_call 补合成结果，防下一轮 400。
        if len(last.tool_calls) > s.max_tool_calls_per_turn:
            tool_messages = tool_messages + skipped_tool_messages(
                last.tool_calls[s.max_tool_calls_per_turn :]
            )

        update: dict[str, Any] = {
            "messages": tool_messages,
            "tool_logs": ordered_logs,
            "tool_iterations": state.get("tool_iterations", 0) + 1,
        }
        # 子图全量模式下 tool_search 命中的 dynamic 工具名写回 disclosed_tools（去重累积），
        # 下一轮子 agent 节点 rebind 时绑上、可调用。白名单模式不会出现 tool_search，返回空。
        disclosed = disclosed_from_tool_calls(tool_calls)
        if disclosed:
            update["disclosed_tools"] = disclosed
            log.info("sub_agent.tool_node.disclosed", tools=disclosed)
        if errors:
            update["error"] = "; ".join(errors)
            update["error_type"] = most_severe_error_type(errors)
        return update

    return tool_node


# ─── 子 agent 节点：recovery ──────────────────────────────────────────


async def _recovery_node(state: SubAgentState, config: RunnableConfig) -> dict:
    """子 agent 错误恢复（精简版，不依赖 PenAgentState）。"""
    error = state.get("error", "") or ""
    error_type = state.get("error_type") or classify_error(error)

    if not error and state.get("tool_iterations", 0) >= state.get("max_tool_iterations", 10):
        error_type = "TOOL_LOOP"
        error = f"工具调用循环：已超过最大迭代次数 {state.get('max_tool_iterations', 10)}"

    if error_type in _NON_RETRYABLE_ERRORS:
        log.warning("sub_agent.recovery.terminal", error_type=error_type)
        return {"error": error, "error_type": f"TERMINAL_{error_type}"}

    attempts = state.get("recovery_attempts", 0) + 1
    backoff_list = _BACKOFF_SECONDS.get(error_type, _BACKOFF_SECONDS["UNKNOWN"])
    backoff_sec = backoff_list[min(attempts - 1, len(backoff_list) - 1)]
    if backoff_sec > 0:
        await asyncio.sleep(backoff_sec)

    hint = _RECOVERY_PROMPTS.get(error_type, _RECOVERY_PROMPTS["UNKNOWN"])
    recovery_msg = HumanMessage(
        content=f"[⚙系统] 恢复指令 #{attempts} | 错误：{error_type}\n{hint}\n详情：{error[:300]}"
    )
    return {
        "messages": [recovery_msg],
        "error": None,
        "error_type": None,
        "recovery_attempts": attempts,
    }


# ─── 子 agent 节点：critic ────────────────────────────────────────────
# enable_critic=True 时由 build_sub_graph 注册（见 harness.core.graph.routes 中的子图路由函数）。不是工厂：不需要 per-agent 配置，与 _recovery_node
# 同款顶层函数形态。


_CRITIC_PROMPT_TEMPLATE = """评估以下输出质量：
任务: {task}
输出: {output}

对以下维度 1-5 打分，返回 JSON：
- completeness: 是否回答了任务所有方面？
- accuracy: 是否有明显事实错误或幻觉？
- actionability: 结果是否可直接使用？
- verdict: PASS (各项≥3) 或 FAIL"""


async def critic_node(state: SubAgentState, config: RunnableConfig) -> dict:
    """评估子 agent 最终回复质量，FAIL 时反馈重试（上限 2 次），否则放行。

    返回值两种形态：
      - 重试：{"messages": [HumanMessage(...)], "critic_attempts": int,
               "error": None, "error_type": None}
      - 通过/放行：{"critic_passed": True}

    fail-open：无 AIMessage、LLM 调用异常、JSON 解析失败或缺字段时均返回
    {"critic_passed": True}，不让 critic 自身异常变成新的错误源。
    """
    messages = state.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not last_ai:
        return {"critic_passed": True}

    output = _extract_text(last_ai.content)
    task_text = _extract_text(messages[0].content) if messages else ""

    s = get_settings()
    model = _get_base_model(
        s.model_low, s.anthropic_api_key, s.anthropic_base_url, s.summarize_max_tokens
    )
    prompt = _CRITIC_PROMPT_TEMPLATE.format(task=task_text[:2000], output=output[:2000])

    resp_text = ""
    try:
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        resp_text = _extract_text(resp.content)

        usage = getattr(resp, "response_metadata", {}).get("usage", {})
        await record_usage(
            state.get("session_id", "_anon"),
            s.model_low,
            usage.get("input_tokens", count_tokens(prompt)),
            usage.get("output_tokens", count_tokens(resp_text)),
        )

        result = json.loads(resp_text)
        verdict = result["verdict"]
        completeness = result["completeness"]
        accuracy = result["accuracy"]
        actionability = result["actionability"]
    except Exception as exc:  # noqa: BLE001
        log.warning("sub_agent.critic.parse_error", exc=str(exc), raw=resp_text[:200])
        return {"critic_passed": True}

    attempts = state.get("critic_attempts", 0)
    log.info(
        "sub_agent.critic.scored",
        verdict=verdict,
        completeness=completeness,
        accuracy=accuracy,
        actionability=actionability,
        attempts=attempts,
    )

    if verdict == "FAIL" and attempts < 2:
        next_attempts = attempts + 1
        feedback = HumanMessage(
            content=(
                f"[⚙Critic #{next_attempts}] "
                f"质量不达标(C={completeness},A={accuracy},P={actionability})。请改进。"
            )
        )
        return {
            "messages": [feedback],
            "critic_attempts": next_attempts,
            "error": None,
            "error_type": None,
        }

    return {"critic_passed": True}
