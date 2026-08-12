"""会话历史管理 — CRUD + 消息查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from harness.app.auth import require_auth
from harness.app.schemas import MessageOut, SessionCreate, SessionOut, SessionUpdate
from harness.infra import db

router = APIRouter(tags=["sessions"], dependencies=[Depends(require_auth)])


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(limit: int = 50):
    sessions = await db.list_sessions(limit=limit)
    return [
        SessionOut(id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at)
        for s in sessions
    ]


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(req: SessionCreate):
    s = await db.create_session(title=req.title)
    return SessionOut(id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at)


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str):
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话不存在：{session_id}")
    return SessionOut(id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def patch_session(session_id: str, req: SessionUpdate):
    ok = await db.update_title(session_id, req.title)
    if not ok:
        raise HTTPException(404, f"会话不存在：{session_id}")
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话不存在：{session_id}")
    return SessionOut(id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    ok = await db.delete_session(session_id)
    if not ok:
        raise HTTPException(404, f"会话不存在：{session_id}")
    return Response(status_code=204)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: str, limit: int = 200):
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话不存在：{session_id}")
    msgs = await db.recent_messages(session_id, n=limit)
    return [
        MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
        for m in msgs
    ]


@router.get("/sessions/{session_id}/phases")
async def list_phases(session_id: str):
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话不存在：{session_id}")
    phases = await db.list_phases(session_id)
    return [
        {
            # 存储主键是 per-会话 hash；对外 id 从 payload 还原成原始逻辑 id（如 "agent"），
            # 保持 GET /phases 契约不变（见 db.upsert_phase 的复合主键说明）
            "id": (p.payload or {}).get("id") or p.id,
            "session_id": p.session_id,
            "parent_id": p.parent_id,
            "type": p.type,
            "status": p.status,
            "label": p.label,
            "payload": p.payload,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in phases
    ]
