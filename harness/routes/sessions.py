"""会话历史管理 — CRUD + 消息查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from harness.app.auth import require_auth
from harness.app.schemas import (
    CompressCommitRequest,
    CompressPreviewOut,
    MessageOut,
    RunEventOut,
    RunSummaryOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from harness.core.context.summarize import compact_session_history
from harness.core.foundation.tokens import count_tokens
from harness.core.graph.providers import resolve_provider
from harness.infra import db
from harness.infra.settings import get_settings

router = APIRouter(tags=["sessions"], dependencies=[Depends(require_auth)])

_ROLE_LABELS = {"user": "用户", "assistant": "助手", "system": "系统"}


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(limit: int = 50):
    sessions = await db.list_sessions(limit=limit)
    return [
        SessionOut(id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at)
        for s in sessions
    ]


@router.get("/runs", response_model=list[RunSummaryOut])
async def list_runs(limit: int = 60):
    rows = await db.list_run_summaries(limit=max(1, min(limit, 200)))
    return [RunSummaryOut(**row) for row in rows]


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


@router.post("/sessions/{session_id}/compress/preview", response_model=CompressPreviewOut)
async def compress_preview(session_id: str):
    """主动压缩「预览」：把当前会话截至此刻的原文压成结构化摘要返回，**不落库**。

    用户可编辑摘要后再调 commit 生效。原文一律保留在 DB，可回退。
    """
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话不存在：{session_id}")

    msgs = await db.messages_upto(session_id)  # 全部历史至今，正序
    if not msgs:
        raise HTTPException(400, "该会话没有可压缩的历史消息")

    upto = msgs[-1].created_at  # 检查点边界 = 此刻最后一条消息的时间
    st = get_settings()

    # 从最近往前保留在 token 上限内的原文；更早部分由已有摘要覆盖（从原文整体重生成）
    kept: list = []
    used = 0
    for m in reversed(msgs):
        t = count_tokens(m.content)
        if kept and used + t > st.compaction_input_max_tokens:
            break
        kept.append(m)
        used += t
    kept.reverse()

    transcript = "\n\n".join(f"{_ROLE_LABELS.get(m.role, m.role)}：{m.content}" for m in kept)
    prev_summary, _ = await db.get_compaction(session_id)

    try:
        summary = await compact_session_history(
            transcript,
            prev_summary=prev_summary,
            model_name=st.model_low,
            provider=resolve_provider(st.model_low_provider, st.model_low),
            max_tokens=st.summarize_max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"压缩失败，请稍后重试：{str(exc)[:200]}") from exc

    return CompressPreviewOut(
        summary=summary,
        upto=upto,
        messages=len(kept),
        tokens_before=used,
        tokens_after=count_tokens(summary),
    )


@router.post("/sessions/{session_id}/compress/commit", status_code=204)
async def compress_commit(session_id: str, req: CompressCommitRequest):
    """主动压缩「提交」：把（可能编辑过的）摘要 + 检查点写入会话，之后按检查点装载历史。"""
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话不存在：{session_id}")
    if not req.summary.strip():
        raise HTTPException(400, "摘要不能为空")
    await db.set_compaction(session_id, req.summary, req.upto)
    return Response(status_code=204)


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


@router.get("/sessions/{session_id}/events", response_model=list[RunEventOut])
async def list_run_events(session_id: str, after_seq: int = 0, limit: int = 1000):
    if await db.get_session(session_id) is None:
        raise HTTPException(404, f"会话不存在：{session_id}")
    rows = await db.list_run_events(
        session_id,
        after_seq=max(0, after_seq),
        limit=max(1, min(limit, 2000)),
    )
    return [
        RunEventOut(seq=row.id, event=row.event, data=row.data, created_at=row.created_at)
        for row in rows
    ]
