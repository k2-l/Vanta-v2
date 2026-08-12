"""结果看板只读查询路由（BLACKBOARD P1 · UI 侧）。

**操作者（人类使用者）视角 —— 跨 engagement 全见**：与 agent 侧 `board` 工具的
L1 隔离（只见当前激活 engagement）不同，这里是平台操作者的总览面板。
可选 `?engagement_id=` / `?kind=` 过滤。secret 类正文不回明文（见 `_utils.artifact_to_dict`）。

写侧不在此暴露：artifact 只由 agent 的 `board` 工具产出（编排层中介，见 docs/BLACKBOARD.md）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from harness.app.auth import require_auth
from harness.infra import db
from harness.routes._utils import artifact_to_dict

router = APIRouter(prefix="/v1", tags=["board"])


@router.get("/artifacts")
async def list_artifacts(
    engagement_id: str | None = None,
    kind: str | None = None,
    _: dict = Depends(require_auth),
) -> list[dict]:
    """看板 artifact 列表（最新在前）。engagement_id 省略=跨 engagement 全见；可按 kind 过滤。"""
    rows = await db.list_artifacts(engagement_id=engagement_id, kind=kind)
    return [artifact_to_dict(r) for r in rows]
