"""POST /chat — SSE 流式对话入口。

同时将 task 状态事件广播到 event_bus，供 WS /ws/chat/{session_id} 订阅者接收。
"""

from __future__ import annotations

import json
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

router = APIRouter(tags=["chat"])
_runtime = AgentRuntime()

# 只广播 WS 专用的 task 状态事件；SSE 已经负责 worker_start/end、tool_call 等流事件，
# 不重复广播，避免前端 applyEvent 对同一事件执行两次。
_BROADCAST_TYPES = {"phase", "task_log"}


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
        yield {"event": "session", "data": session_id}
        async for ev in _runtime.stream_events(
            req.message, session_id, execution_env=req.execution_env or "local"
        ):
            yield ev
            # Broadcast task-related events to WebSocket subscribers
            # ev is always dict[str, str] — isinstance check is redundant
            if ev.get("event") in _BROADCAST_TYPES:
                try:
                    payload = json.loads(ev.get("data", "{}"))
                    await event_bus.publish(session_id, payload)
                    if ev.get("event") == "phase" and payload.get("id"):
                        # 顺序 await（而非 fire-and-forget create_task）：保证同一 phase_id
                        # 的 running→ok 按发射顺序落库（独立事务并发会让 ok 被迟到的 running
                        # 覆盖成 stale 状态），且任务引用不丢失（避免被 GC 提前回收），
                        # upsert 异常也归入下方 try/except 统一记日志。
                        await db.upsert_phase(payload["id"], session_id, payload)
                except Exception as e:
                    log.warning("chat.broadcast.failed", session_id=session_id, error=str(e)[:120])

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


@router.post("/chat/approvals/{call_id}")
async def submit_approval_decision(
    call_id: str,
    decision: ApprovalDecision,
    _claims: Annotated[dict, Depends(require_auth)],
):
    """HITL 审批门决策端点：批准/拒绝一个挂起的 approval_required 请求。

    对应 harness/infra/approvals.py 的 request_approval() 阻塞等待；
    见 docs/superpowers/specs/2026-06-14-approval-gate-design.md。
    """
    if not resolve_approval(call_id, decision.approved):
        raise HTTPException(status_code=404, detail="审批请求不存在或已失效")
    return {"ok": True}
