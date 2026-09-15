"""append-only 哈希链审计账本 —— 防篡改的动作留痕。

只提供 append / query / verify_chain（无 update/delete）。每条
  entry_hash = sha256(prev_hash + 规范化内容)
改任一历史行会使其后所有 entry_hash 对不上，verify_chain 可检出。
append 用进程内锁串行化以取到正确 prev_hash（单进程；跨进程另需 DB 层序列化）。
时间戳存 created_at 但**不进哈希**——避免 DB 往返的时区 / 精度差导致 verify 误报。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from harness.infra.db import AuditLedgerRecord, new_id, session_factory
from harness.infra.logging import log

_append_lock = asyncio.Lock()
_GENESIS = "0" * 64


def _content(
    engagement_id: str | None,
    session_id: str,
    actor: str,
    action: str,
    target: str,
    command: str,
    decision: str,
    detail: dict[str, Any] | None,
) -> dict[str, Any]:
    """参与哈希的内容字段（键固定；顺序无关，由 _digest sort_keys）。"""
    return {
        "engagement_id": engagement_id,
        "session_id": session_id,
        "actor": actor,
        "action": action,
        "target": target,
        "command": command,
        "decision": decision,
        "detail": detail or {},
    }


def _digest(prev_hash: str, content: dict[str, Any]) -> str:
    """prev_hash + 规范化内容 的 sha256（链式哈希）。"""
    body = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256((prev_hash + "\n" + body).encode("utf-8")).hexdigest()


async def append_audit(
    action: str,
    *,
    engagement_id: str | None = None,
    session_id: str = "",
    actor: str = "agent",
    target: str = "",
    command: str = "",
    decision: str = "",
    detail: dict[str, Any] | None = None,
) -> str:
    """追加一条审计（append-only）。返回 entry_hash。

    审计失败不上抛、不阻断主流程（记 warning 返回空串）——护栏动作本身已由其它层保证。
    """
    content = _content(engagement_id, session_id, actor, action, target, command, decision, detail)
    try:
        async with _append_lock:
            sf = session_factory()
            async with sf() as db:
                prev = (
                    await db.execute(
                        select(AuditLedgerRecord.entry_hash)
                        .order_by(
                            AuditLedgerRecord.created_at.desc(), AuditLedgerRecord.id.desc()
                        )
                        .limit(1)
                    )
                ).scalar() or _GENESIS
                entry_hash = _digest(prev, content)
                db.add(
                    AuditLedgerRecord(
                        id=new_id(),
                        engagement_id=engagement_id,
                        session_id=session_id,
                        actor=actor,
                        action=action,
                        target=target,
                        command=command,
                        decision=decision,
                        detail=detail,
                        prev_hash=prev,
                        entry_hash=entry_hash,
                        created_at=datetime.now(UTC),
                    )
                )
                await db.commit()
                return entry_hash
    except Exception as exc:  # noqa: BLE001 —— 审计失败不阻断主流程
        log.warning("audit_ledger.append_failed", action=action, exc=str(exc)[:200])
        return ""


async def query_audit(
    engagement_id: str | None = None, limit: int = 100, action: str | None = None
) -> list[AuditLedgerRecord]:
    """查询审计记录（按时间倒序，可按 engagement / action 过滤）。"""
    sf = session_factory()
    async with sf() as db:
        q = select(AuditLedgerRecord).order_by(AuditLedgerRecord.created_at.desc()).limit(limit)
        if engagement_id is not None:
            q = q.where(AuditLedgerRecord.engagement_id == engagement_id)
        if action is not None:
            q = q.where(AuditLedgerRecord.action == action)
        return list((await db.execute(q)).scalars().all())


async def verify_chain(limit: int = 100_000) -> tuple[bool, str]:
    """重算全链哈希，检测篡改 / 断链。返回 (完好, 说明)。"""
    sf = session_factory()
    async with sf() as db:
        rows = list(
            (
                await db.execute(
                    select(AuditLedgerRecord)
                    .order_by(AuditLedgerRecord.created_at, AuditLedgerRecord.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    prev = _GENESIS
    for row in rows:
        content = _content(
            row.engagement_id, row.session_id, row.actor, row.action, row.target, row.command, row.decision, row.detail
        )
        if row.prev_hash != prev:
            return False, f"断链于 {row.id}：prev_hash 不匹配"
        if _digest(prev, content) != row.entry_hash:
            return False, f"篡改于 {row.id}：entry_hash 重算不符"
        prev = row.entry_hash
    return True, f"链完好（{len(rows)} 条）"
