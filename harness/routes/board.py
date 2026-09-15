"""结果看板只读查询路由（BLACKBOARD P1 · UI 侧）。

**操作者（人类使用者）视角 —— 跨 engagement 全见**：与 agent 侧 `board` 工具的
L1 隔离（只见当前激活 engagement）不同，这里是平台操作者的总览面板。
可选 `?engagement_id=` / `?kind=` 过滤。secret 类正文不回明文（见 `_utils.artifact_to_dict`）。

写侧不在此暴露：artifact 只由 agent 的 `board` 工具产出（编排层中介，见 docs/BLACKBOARD.md）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from harness.app.auth import require_auth
from harness.infra import db
from harness.routes._utils import artifact_to_dict

router = APIRouter(prefix="/v1", tags=["board"])


@router.get("/artifacts")
async def list_artifacts(
    _claims: Annotated[dict, Depends(require_auth)],
    engagement_id: str | None = None,
    kind: str | None = None,
    session_id: str | None = None,
) -> list[dict]:
    """看板 artifact 列表；可按 engagement、类型或来源会话过滤。"""
    rows = await db.list_artifacts(
        engagement_id=engagement_id,
        kind=kind,
        source_session_id=session_id,
    )
    return [artifact_to_dict(r) for r in rows]


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    _claims: Annotated[dict, Depends(require_auth)],
) -> dict:
    """单个产物详情；secret 仍只返回元数据，供 Rust Core 安全导出。"""
    row = await db.get_artifact(artifact_id)
    if row is None:
        raise HTTPException(404, "产物不存在")
    return artifact_to_dict(row)
