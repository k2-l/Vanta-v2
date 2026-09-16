"""WebSocket /ws/chat/{session_id} — 实时 Task 状态推送。

协议：
  1. 客户端连接后发送 {"type": "subscribe", "session_id": "<id>"}
  2. 服务器回复 {"type": "subscribed", "session_id": "<id>"}
  3. 服务器持续推送 event_bus 中该 session 的事件，直到连接关闭
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from harness.app.auth import verify_access_token
from harness.infra.event_bus import event_bus
from harness.infra.logging import log

router = APIRouter(tags=["ws"])


@router.websocket("/ws/chat/{session_id}")
async def ws_chat(session_id: str, websocket: WebSocket):
    # JWT 验证：从 query param 或 Authorization header 读取 token
    token = _extract_token(websocket)
    if not token:
        await websocket.close(code=4001, reason="missing token")
        return
    try:
        await verify_access_token(token)
    except Exception:
        await websocket.close(code=4001, reason="invalid token")
        return

    await websocket.accept()
    log.info("ws.connected", session_id=session_id)

    async with event_bus.subscribe(session_id) as q:
        # 发送订阅确认
        await websocket.send_text(json.dumps({"type": "subscribed", "session_id": session_id}))

        try:
            while True:
                # 等待事件或客户端断连（两者并发）
                recv_task = asyncio.create_task(websocket.receive_text())
                get_task  = asyncio.create_task(q.get())
                done, pending = await asyncio.wait(
                    {recv_task, get_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

                for task in done:
                    if task is get_task:
                        event = task.result()
                        await websocket.send_text(json.dumps(event))
                    elif task is recv_task:
                        try:
                            task.result()  # 触发 WebSocketDisconnect / RuntimeError
                        except (WebSocketDisconnect, RuntimeError):
                            return  # 客户端已断连，退出 handler

        except (WebSocketDisconnect, RuntimeError):
            log.info("ws.disconnected", session_id=session_id)


def _extract_token(ws: WebSocket) -> str | None:
    """Extract bearer token from Authorization header or ?token= query param."""
    auth = ws.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ws.query_params.get("token")
