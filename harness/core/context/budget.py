"""Token 预算管理系统。

限额由 Settings 配置（session_token_limit / daily_token_limit / model_context_window）。
用量持久化到 PostgreSQL token_usage 表。
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import case as sa_case
from sqlalchemy import func, select

from harness.core.context.usage import tracker
from harness.infra.db import TokenUsage, session_factory
from harness.infra.logging import log
from harness.infra.settings import get_settings

SUMMARY_TRIGGER = 150_000  # tokens（预留 50K 给 summary + 新消息）

# ─── 预算管理 ─────────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """超出 token 预算时抛出。"""

    def __init__(self, kind: str, used: int, limit: int):
        self.kind = kind
        self.used = used
        self.limit = limit
        super().__init__(f"{kind} token 预算超限：{used:,} / {limit:,}")


async def record_usage(
    session_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """写入一条用量记录（DB 持久化 + 内存 tracker 更新）。"""
    tracker().add(session_id, model, input_tokens, output_tokens)
    async with session_factory()() as db:
        rec = TokenUsage(
            id=uuid.uuid4().hex[:12],
            session_id=session_id,
            date=date.today(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        db.add(rec)
        await db.commit()
    log.debug("token_usage.record", session=session_id, in_t=input_tokens, out_t=output_tokens)


async def _sum_tokens(session, predicate) -> int:
    """Execute a single-row SUM query with the given WHERE predicate and return the result."""
    result = await session.execute(
        select(
            func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0)
        ).where(predicate)
    )
    return int(result.scalar() or 0)


async def get_session_tokens(session_id: str) -> int:
    """返回本会话累计消耗的 token 数。"""
    async with session_factory()() as db:
        return await _sum_tokens(db, TokenUsage.session_id == session_id)


async def get_daily_tokens() -> int:
    """返回今日全局消耗的 token 数。"""
    async with session_factory()() as db:
        return await _sum_tokens(db, TokenUsage.date == date.today())


async def check_budget(session_id: str) -> tuple[int, int]:
    """检查预算，超限则抛 BudgetExceeded，否则返回 (session_used, daily_used)。"""
    session_used, daily_used = await _fetch_usage(session_id)
    s = get_settings()

    if session_used >= s.session_token_limit:
        raise BudgetExceeded("SESSION", session_used, s.session_token_limit)
    if daily_used >= s.daily_token_limit:
        raise BudgetExceeded("DAILY", daily_used, s.daily_token_limit)

    return session_used, daily_used


async def _fetch_usage(session_id: str) -> tuple[int, int]:
    """单次查询同时获取会话用量和今日全局用量。"""
    today = date.today()
    async with session_factory()() as db:
        r = await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        sa_case(
                            (
                                TokenUsage.session_id == session_id,
                                TokenUsage.input_tokens + TokenUsage.output_tokens,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("session_tokens"),
                func.coalesce(
                    func.sum(
                        sa_case(
                            (
                                TokenUsage.date == today,
                                TokenUsage.input_tokens + TokenUsage.output_tokens,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("daily_tokens"),
            ).where((TokenUsage.session_id == session_id) | (TokenUsage.date == today))
        )
        row = r.one()
    return int(row.session_tokens), int(row.daily_tokens)


async def get_budget_status(session_id: str) -> dict:
    """返回预算状态摘要（供前端展示）。"""
    session_used, daily_used = await _fetch_usage(session_id)
    s = get_settings()

    def _percent(used: int, limit: int) -> float:
        # Settings 已拒绝非正数；这里仍防御旧配置或直接构造的 settings stub。
        return round(used / limit * 100, 1) if limit > 0 else (100.0 if used else 0.0)

    return {
        "session": {
            "used": session_used,
            "limit": s.session_token_limit,
            "percent": _percent(session_used, s.session_token_limit),
        },
        "daily": {
            "used": daily_used,
            "limit": s.daily_token_limit,
            "percent": _percent(daily_used, s.daily_token_limit),
        },
        "context_window": s.model_context_window,
        "compression_threshold": s.context_compression_threshold,
        "compression_enabled": s.context_compression_enabled,
    }
