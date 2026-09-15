"""POST /chat — SSE 流式对话入口。

同时将 task 状态事件广播到 event_bus，供 WS /ws/chat/{session_id} 订阅者接收。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from harness.app.auth import require_auth
from harness.app.schemas import ChatRequest
from harness.core.runtime import AgentRuntime
from harness.infra import db
from harness.infra.event_bus import event_bus
from harness.infra.logging import log
from harness.security.approvals import list_pending, resolve_approval
from harness.security.audit_ledger import append_audit, query_audit
from harness.security.redaction import redact

router = APIRouter(tags=["chat"])
_runtime = AgentRuntime()

# 只广播 WS 专用的 task 状态事件；SSE 已经负责 worker_start/end、tool_call 等流事件，
# 不重复广播，避免前端 applyEvent 对同一事件执行两次。
_BROADCAST_TYPES = {"phase", "task_log"}
# 正文由 messages 表保存；这里只持久化重建运行详情所需的结构化遥测，避免逐 token 写库。
_RUN_HISTORY_TYPES = {
    "tool_call",
    "tool_result",
    "tool_error",
    "worker_start",
    "worker_end",
    "usage",
    "phase",
    "task_log",
    "done",
}
_SENSITIVE_EVENT_KEYS = (
    "authorization",
    "api_key",
    "access_key",
    "private_key",
    "password",
    "passwd",
    "secret",
    "token",
)


def _redact_event_value(value):
    """递归脱敏后再写运行历史，避免工具输入/输出中的高置信凭据落盘。"""

    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, list):
        return [_redact_event_value(item) for item in value]
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if isinstance(item, str) and any(marker in normalized_key for marker in _SENSITIVE_EVENT_KEYS):
                redacted[key] = "[REDACTED:CREDENTIAL]"
            else:
                redacted[key] = _redact_event_value(item)
        return redacted
    return value


async def _record_runtime_event(session_id: str, event: dict[str, str]) -> None:
    event_name = event.get("event", "")
    if event_name not in _BROADCAST_TYPES | _RUN_HISTORY_TYPES:
        return
    try:
        payload = json.loads(event.get("data", "{}"))
        if event_name in _RUN_HISTORY_TYPES:
            await db.append_run_event(
                session_id,
                event_name,
                _redact_event_value(payload),
            )
        if event_name in _BROADCAST_TYPES:
            await event_bus.publish(session_id, payload)
            if event_name == "phase" and payload.get("id"):
                # 同一 phase_id 的 running→ok 必须按发射顺序落库，避免迟到写覆盖终态。
                await db.upsert_phase(payload["id"], session_id, payload)
    except Exception as exc:  # noqa: BLE001
        # 遥测落库/广播是运行可观测性，不得阻断对话正文继续返回。
        log.warning(
            "chat.runtime_event_record.failed",
            session_id=session_id,
            event=event_name,
            error=str(exc)[:120],
        )


@router.post("/chat")
async def chat(
    req: ChatRequest,
    _claims: Annotated[dict, Depends(require_auth)],
):
    session_id = req.session_id
    if not session_id:
        s = await db.create_session()
        session_id = s.id

    async def event_gen():
        event_queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()

        async def history_writer() -> None:
            while (event := await event_queue.get()) is not None:
                await _record_runtime_event(session_id, event)

        writer = asyncio.create_task(history_writer())
        try:
            yield {"event": "session", "data": session_id}
            async for ev in _runtime.stream_events(
                req.message, session_id, execution_env=req.execution_env or "local"
            ):
                # 单写入协程保持事件顺序，同时不让数据库提交延迟 SSE 正文。
                event_queue.put_nowait(ev)
                yield ev
        finally:
            event_queue.put_nowait(None)
            try:
                await asyncio.wait_for(asyncio.shield(writer), timeout=5)
            except TimeoutError:
                writer.cancel()
                try:
                    await writer
                except asyncio.CancelledError:
                    pass
                log.warning("chat.runtime_event_flush.timeout", session_id=session_id)
            except asyncio.CancelledError:
                # 客户端断开时 writer 仍由事件循环持有并完成已排队的遥测。
                pass

    return EventSourceResponse(event_gen())


@router.get("/chat/approvals")
async def list_approvals(_claims: Annotated[dict, Depends(require_auth)]):
    """待处理审批队列（全局，进程内内存）。桌面/Web HITL UI 轮询此端点获取挂起项。

    每项：call_id / tool_name / message / session_id / requested_at / expires_at。
    决策仍走 POST /chat/approvals/{call_id}；resolve 后该项从队列消失。
    """
    return list_pending()


class ApprovalDecision(BaseModel):
    approved: bool


def _decision_record(row: db.AuditLedgerRecord) -> dict:
    """审计账本行 → 审批决策历史项。decision_id 来自 detail（独立稳定 id）；
    entry_hash 作为审计证据随行返回，不充当决策 id。"""
    detail = row.detail or {}
    return {
        "decision_id": detail.get("decision_id", ""),
        "call_id": detail.get("call_id", ""),
        "tool_name": detail.get("tool_name", ""),
        "session_id": row.session_id,
        "decision": row.decision,
        "risk": detail.get("risk", ""),
        "risk_source": detail.get("risk_source", ""),
        "target": row.target,
        "scope": detail.get("scope", ""),
        "impact": detail.get("impact", ""),
        "message": row.command,
        "decided_at": row.created_at.isoformat() if row.created_at else "",
        "entry_hash": row.entry_hash,  # 审计证据（哈希链条目），非决策 id
    }


@router.get("/chat/approvals/history")
async def list_approval_history(
    _claims: Annotated[dict, Depends(require_auth)],
    limit: int = 100,
):
    """审批决策历史（来自哈希链审计账本，服务端权威记录）。

    与 GET /chat/approvals（进程内挂起队列）互补：此处是已决策的持久化历史，
    进程重启后仍可查询；每项含独立 decision_id + entry_hash 审计证据。
    """
    rows = await query_audit(action="tool_approval", limit=limit)
    return [_decision_record(r) for r in rows]


@router.post("/chat/approvals/{call_id}")
async def submit_approval_decision(
    call_id: str,
    decision: ApprovalDecision,
    _claims: Annotated[dict, Depends(require_auth)],
):
    """HITL 审批门决策端点：批准/拒绝一个挂起的 approval_required 请求。

    对应 harness/security/approvals.py 的 request_approval() 阻塞等待；
    决策以独立 decision_id 标识，并写入哈希链审计账本（entry_hash 为审计证据）。
    审计写入失败不阻断决策（append_audit fail-open 返回空串），此时 audit_recorded=False。
    """
    meta = resolve_approval(call_id, decision.approved)
    if meta is None:
        raise HTTPException(status_code=404, detail="审批请求不存在或已失效")

    decision_id = uuid.uuid4().hex  # 独立稳定 id，不依赖审计写入成功
    decision_str = meta["decision"]  # "approved" | "rejected"
    entry_hash = await append_audit(
        "tool_approval",
        session_id=meta.get("session_id", ""),
        actor="human",
        target=meta.get("target", ""),
        command=meta.get("message", ""),
        decision=decision_str,
        detail={
            "decision_id": decision_id,
            "call_id": call_id,
            "tool_name": meta.get("tool_name", ""),
            "risk": meta.get("risk", ""),
            "risk_source": meta.get("risk_source", ""),
            "scope": meta.get("scope", ""),
            "impact": meta.get("impact", ""),
        },
    )
    return {
        "ok": True,
        "decision_id": decision_id,
        "decision": decision_str,
        "audit_recorded": bool(entry_hash),
        "entry_hash": entry_hash,  # 空串表示审计写入失败（决策仍生效）
    }
