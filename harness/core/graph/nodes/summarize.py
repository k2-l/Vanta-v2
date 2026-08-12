"""Rolling-summary node for the main LangGraph agent."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from harness.core.context.budget import record_usage
from harness.core.foundation.state import PenAgentState, SubgoalEntry
from harness.core.foundation.tokens import count_messages_tokens, count_tokens
from harness.core.graph.models import _get_base_model
from harness.infra.logging import log
from harness.infra.settings import get_settings

_SUMMARIZE_SYSTEM_PROMPT = "你是摘要助手。用简洁中文总结以下对话历史，保留关键事实和结论。"


def _split_completed_subgoals(
    active_subgoals: list[SubgoalEntry], n: int
) -> tuple[list[dict], list[SubgoalEntry]]:
    """按 message_index 把 active_subgoals 分为已完成且可掩码项和剩余项。

    已完成 = 存在更晚的 subgoal（即非最后一项）且其结束边界 <= n（完全在待压缩区间内）。
    跨边界的当前进行中 subgoal（最后一项，无结束边界）始终归入 remaining，
    走原有 LLM 摘要路径。
    """
    if not active_subgoals:
        return [], []
    masked: list[dict] = []
    remaining: list[SubgoalEntry] = []
    for i, entry in enumerate(active_subgoals):
        start = entry["message_index"]
        end = active_subgoals[i + 1]["message_index"] if i + 1 < len(active_subgoals) else None
        if end is not None and end <= n:
            masked.append({**entry, "_start": start, "_end": end})
        else:
            remaining.append(entry)
    return masked, remaining


async def summarize_node(state: PenAgentState, config: RunnableConfig) -> dict:
    """token 超阈值时压缩旧消息 → Rolling Summary，保留最近 N 条（可配置）。

    子目标感知压缩：已完成且完全落在待压缩区间内的 subgoal 直接替换为掩码文本
    （零 LLM 调用）；剩余消息走原有 LLM 摘要逻辑。
    """
    s = get_settings()  # 单次调用，后续所有字段从 s 读取
    messages = state.get("messages", [])

    if len(messages) <= s.summarize_keep_recent:
        return {}

    old_msgs = messages[: -s.summarize_keep_recent]
    recent_msgs = messages[-s.summarize_keep_recent :]
    n = len(old_msgs)

    masked_subgoals, remaining_subgoals = _split_completed_subgoals(
        state.get("active_subgoals", []), n
    )
    masked_ranges = [(e["_start"], e["_end"]) for e in masked_subgoals]
    llm_input_msgs = [
        m for idx, m in enumerate(old_msgs) if not any(start <= idx < end for start, end in masked_ranges)
    ]
    mask_lines = [
        f"[已完成: {e['text']}，{e['_end'] - e['_start']} 条消息已压缩]" for e in masked_subgoals
    ]

    if llm_input_msgs:
        # 显式 resolve summary model，确保 lru_cache key 是具体模型名而非空字符串
        model = _get_base_model(
            s.model_low,
            s.anthropic_api_key,
            s.anthropic_base_url,
            s.summarize_max_tokens,
            s.thinking_budget_low if s.enable_extended_thinking else None,
        )

        history_text = "\n".join(
            f"[{m.__class__.__name__}] "
            f"{(m.content[:800] if isinstance(m.content, str) else str(m.content)[:800])}"
            for m in llm_input_msgs
        )

        try:
            resp = await model.ainvoke(
                [
                    SystemMessage(content=_SUMMARIZE_SYSTEM_PROMPT),
                    HumanMessage(content=f"请摘要：\n\n{history_text}"),
                ]
            )
            llm_summary = resp.content if isinstance(resp.content, str) else str(resp.content)

            usage = getattr(resp, "response_metadata", {}).get("usage", {})
            await record_usage(
                state.get("session_id", "_anon"),
                s.model_low,
                usage.get("input_tokens", count_tokens(history_text)),
                usage.get("output_tokens", count_tokens(llm_summary)),
            )
        except Exception:  # noqa: BLE001
            llm_summary = f"[旧消息摘要：共 {len(llm_input_msgs)} 条已压缩]"
    else:
        llm_summary = ""

    new_summary = "\n".join(mask_lines + ([llm_summary] if llm_summary else []))

    prev = state.get("rolling_summary", "")
    combined = f"{prev}\n\n{new_summary}".strip() if prev else new_summary

    new_active_subgoals = [
        {**e, "message_index": max(0, e["message_index"] - n)} for e in remaining_subgoals
    ]

    new_token_count = count_messages_tokens(recent_msgs)
    log.info(
        "rolling_summary.done",
        compressed=len(old_msgs),
        masked_subgoals=len(masked_subgoals),
        kept=len(recent_msgs),
        tokens=new_token_count,
    )

    # 旧消息用 RemoveMessage 从 LangGraph 状态中删除
    remove_ops = [RemoveMessage(id=m.id) for m in old_msgs if m.id is not None]

    # 压缩后仍超限：注入终止提示，由 route_after_summarize 路由到 END
    if new_token_count >= s.context_compression_threshold:
        log.warning(
            "context_compression.still_over_limit",
            tokens=new_token_count,
            threshold=s.context_compression_threshold,
        )
        abort_msg = AIMessage(content="上下文过长，压缩后仍超出限制，无法继续对话。请开启新会话。")
        return {
            "messages": remove_ops + [abort_msg],
            "rolling_summary": combined,
            "active_subgoals": new_active_subgoals,
            "token_count": new_token_count,
            "error": "CONTEXT_TOO_LONG",
            "error_type": "CONTEXT_TOO_LONG",
        }

    return {
        "messages": remove_ops,
        "rolling_summary": combined,
        "active_subgoals": new_active_subgoals,
        "token_count": new_token_count,
    }
