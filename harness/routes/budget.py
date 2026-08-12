"""Token 预算查询 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from harness.app.auth import require_auth
from harness.core.context.budget import get_budget_status

router = APIRouter(tags=["budget"], dependencies=[Depends(require_auth)])


@router.get("/budget/{session_id}")
async def session_budget(session_id: str) -> dict:
    """返回指定会话的 token 预算状态。"""
    return await get_budget_status(session_id)
