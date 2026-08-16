<<<<<<< HEAD
"""Preprocess node for context loading, budget checks, and token accounting."""
=======
"""Preprocess node for context loading, budget checks, and token accounting.

对齐 Claude Code 后不再做技能路由：L1 清单（全部已启用 agent+skill）恒注入，
技能的「选择」交给模型读 description 完成。本节点只负责预算检查、记忆召回、
L1 清单装载与 token 计数。
"""
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

from __future__ import annotations

import asyncio
import re

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from harness.core.capabilities.memory import _merge_memories, recall_as_context
from harness.core.context.budget import BudgetExceeded, check_budget
from harness.core.context.builder import load_and_build as _load_l1
from harness.core.context.builder import load_dep_context as _load_deps
from harness.core.foundation.state import PenAgentState
from harness.core.foundation.tokens import count_messages_tokens, count_tokens
from harness.infra.logging import log
from harness.infra.settings import get_settings
<<<<<<< HEAD
from harness.skills.loader import (
    _build_scratchpad,
    _do_skill_routing,
    _extract_profile_keywords,
    _merge_skill_scores,
)
=======
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

_CLAUSE_SPLIT_RE = re.compile(r"[。？！\?\!\.]")


<<<<<<< HEAD
# ─── 激活内容加载 ────────────────────────────────────────────────────


async def _load_active_context() -> str:
    """从数据库加载 active Agent + Skill 的 L1 清单（带 TTL 缓存）。"""
=======
# ─── 上下文加载 ──────────────────────────────────────────────────────


async def _load_active_context() -> str:
    """加载 Agent + Skill 的 L1 清单（带 TTL 缓存）。"""
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    try:
        return await _load_l1()
    except Exception as exc:  # noqa: BLE001
        log.warning("load_active_context.failed", exc=str(exc)[:100])
        return ""


async def _load_dep_context() -> str:
<<<<<<< HEAD
    """加载 active 实体的依赖树（带 TTL 缓存）。空树跳过。"""
=======
    """依赖上下文（文件系统模式下为空，保留占位）。"""
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    try:
        return await _load_deps()
    except Exception as exc:  # noqa: BLE001
        log.warning("load_dep_context.failed", exc=str(exc)[:100])
        return ""


<<<<<<< HEAD
# ─── 節點 1：preprocess — helper functions ───────────────────────────


=======
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
def _extract_user_query(state: PenAgentState, session_id: str) -> str:
    """Extract the text of the latest HumanMessage from state."""
    _msgs = state.get("messages", [])
    last_msg = _msgs[-1] if _msgs else None
    if not isinstance(last_msg, HumanMessage):
        return ""
    if isinstance(last_msg.content, str):
        return last_msg.content
    if isinstance(last_msg.content, list):
        query = " ".join(
            b.get("text", "")
            for b in last_msg.content
            if isinstance(b, dict) and b.get("type") == "text"
        )
        if not query:
            log.warning("preprocess.multimodal_no_text", session_id=session_id)
        return query
    return ""


<<<<<<< HEAD
async def _preprocess_with_query(
    state: PenAgentState,
    user_query: str,
    profile: str,
    s,
) -> tuple[str, str, str, str | None]:
    """Run the full dual-layer skill matching + memory recall path.

    Returns (memories, skill_context, entity_dep_ctx, new_active_skill).
    """
    from harness.infra.vector import search_skills_semantic

    profile_keywords = _extract_profile_keywords(profile)
    augmented_query = (
        f"{user_query} {' '.join(profile_keywords)}" if profile_keywords else user_query
    )

    sub_queries: list[str] = [user_query]
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(user_query) if c.strip()]
    for c in clauses[:2]:
        if c != user_query and len(c) >= 5:
            sub_queries.append(c)

    recall_tasks = [asyncio.to_thread(recall_as_context, q, k=s.memory_top_k) for q in sub_queries]

    prior_active_skill = state.get("active_skill")

    (
        raw_results,
        entity_dep_ctx,
        routing_result,
        embed_hits,
        embed_hits_profile,
    ) = await asyncio.gather(
        asyncio.gather(*recall_tasks),
        _load_dep_context(),
        _do_skill_routing(user_query, prior_active_skill),
        asyncio.to_thread(search_skills_semantic, user_query, k=5),
        asyncio.to_thread(search_skills_semantic, augmented_query, k=5),
    )
    router_hits_set, new_active_skill = routing_result

    matched_skills, score_map = _merge_skill_scores(router_hits_set, embed_hits, embed_hits_profile)
    memories = _merge_memories(raw_results, s.memory_top_k)

    if matched_skills:
        from harness.core.context.builder import load_matched_block

        skill_context = await load_matched_block(matched_skills=matched_skills)
    else:
        skill_context = await _load_active_context()

    # Attach scratchpad annotation to the profile_keywords we already computed
    scratchpad = _build_scratchpad(score_map, profile_keywords)
    # Return scratchpad as part of entity_dep_ctx placeholder; caller handles it
    # We return scratchpad via a wrapper tuple to keep signature tidy
    return memories, skill_context, entity_dep_ctx or "", new_active_skill, scratchpad  # type: ignore[return-value]


=======
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
# ─── 節點 1：preprocess ───────────────────────────────────────────────


async def preprocess_node(state: PenAgentState, config: RunnableConfig) -> dict:
<<<<<<< HEAD
    """装载上下文，检查 token 预算，重置 Scratchpad。"""
=======
    """装载 L1 清单与记忆，检查 token 预算。"""
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    s = get_settings()
    session_id = state.get("session_id", "")

    # ── 预算检查 ──────────────────────────────────────────────────────
    try:
        session_used, daily_used = await check_budget(session_id)
        log.debug("preprocess.budget_ok", session_used=session_used, daily_used=daily_used)
    except BudgetExceeded as e:
        log.warning("preprocess.budget_exceeded", kind=e.kind, used=e.used, limit=e.limit)
        budget_msg = AIMessage(
            content=f"任务已停止：本次会话的工具调用预算已耗尽（已用 {e.used} 次，上限 {e.limit} 次）。请开启新会话继续。"
        )
        return {
            "messages": [budget_msg],
            "error": str(e),
            "error_type": f"BUDGET_{e.kind}",
            "scratchpad": "",
        }

    # ── 提取用户 query ────────────────────────────────────────────────
    _msgs = state.get("messages", [])
    user_query = _extract_user_query(state, session_id)
    profile = state.get("profile") or ""  # runtime.py 在 initial_state 里已加载

<<<<<<< HEAD
    # ── 双层匹配 + profile 过滤 ───────────────────────────────────────
    if user_query:
        (
            memories,
            skill_context,
            entity_dep_ctx,
            new_active_skill,
            scratchpad,
        ) = await _preprocess_with_query(state, user_query, profile, s)
=======
    # ── 记忆召回（query 相关）+ L1 清单注入（全部已启用）───────────────
    if user_query:
        sub_queries: list[str] = [user_query]
        clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(user_query) if c.strip()]
        for c in clauses[:2]:
            if c != user_query and len(c) >= 5:
                sub_queries.append(c)
        recall_tasks = [
            asyncio.to_thread(recall_as_context, q, k=s.memory_top_k) for q in sub_queries
        ]
        raw_results, skill_context, entity_dep_ctx = await asyncio.gather(
            asyncio.gather(*recall_tasks),
            _load_active_context(),
            _load_dep_context(),
        )
        memories = _merge_memories(raw_results, s.memory_top_k)
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    else:
        memories = ""
        skill_context, entity_dep_ctx = await asyncio.gather(
            _load_active_context(),
            _load_dep_context(),
        )
<<<<<<< HEAD
        entity_dep_ctx = entity_dep_ctx or ""
        scratchpad = ""
        new_active_skill = state.get("active_skill")

    # ── Token 计数 ────────────────────────────────────────────────────
    token_count = count_messages_tokens(_msgs)
    extra = (
=======

    # ── Token 计数 ────────────────────────────────────────────────────
    token_count = count_messages_tokens(_msgs)
    token_count += (
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
        count_tokens(state.get("rolling_summary", "") or "")
        + count_tokens(memories or "")
        + count_tokens(skill_context or "")
        + count_tokens(profile or "")
        + count_tokens(entity_dep_ctx or "")
    )
<<<<<<< HEAD
    token_count += extra
=======
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

    log.info("preprocess", session_id=session_id, msg_count=len(_msgs), tokens=token_count)

    return {
        "recalled_memories": memories,
        "token_count": token_count,
        "skill_context": skill_context,
<<<<<<< HEAD
        "entity_dep_context": entity_dep_ctx,
        "active_skill": new_active_skill,
        "scratchpad": scratchpad,
=======
        "entity_dep_context": entity_dep_ctx or "",
        "scratchpad": "",
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
        "tool_logs": [],
        "tool_iterations": 0,
        "error": None,
        "error_type": None,
    }
