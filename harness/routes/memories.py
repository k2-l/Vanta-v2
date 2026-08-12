"""经验记忆 API — 向量存储的读写接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from harness.app.auth import require_auth
from harness.app.schemas import MemoryItem, MemorySearchRequest, RememberRequest, RememberResponse
from harness.core.capabilities.memory import (
    clear_for_session,
    list_for_session,
    recall_with_meta,
    remember,
)

router = APIRouter(tags=["memories"], dependencies=[Depends(require_auth)])


@router.post("/memory/remember", response_model=RememberResponse)
async def memory_remember(req: RememberRequest):
    mid = remember(req.text, session_id=req.session_id, role=req.role)
    return RememberResponse(id=mid)


@router.get("/memory/list", response_model=list[MemoryItem])
async def memory_list(session_id: str, limit: int = 50):
    items = list_for_session(session_id, limit=limit)
    return [
        MemoryItem(id=i["id"], text=i["text"], metadata=i.get("metadata") or {})
        for i in items
    ]


@router.post("/memory/search", response_model=list[MemoryItem])
async def memory_search(req: MemorySearchRequest):
    res = recall_with_meta(req.query, k=req.k)
    return [
        MemoryItem(
            id="",
            text=r["text"],
            metadata=r.get("metadata") or {},
            distance=r.get("distance"),
        )
        for r in res
    ]


@router.delete("/memory/clear")
async def memory_clear(session_id: str):
    n = clear_for_session(session_id)
    return {"deleted": n}
