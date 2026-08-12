"""GET /config  · PATCH /config — 运行时配置读写。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from harness.app.auth import require_auth
from harness.infra import config_store
from harness.infra.settings import get_settings

router = APIRouter(tags=["config"])

# 允许前端读写的字段白名单
EDITABLE: set[str] = {
    # 模型接口
    "anthropic_api_key", "anthropic_auth_token", "anthropic_base_url",
    # 三档模型
    "model_high", "model_mid", "model_low",
    # 功能开关
    "context_compression_enabled", "enable_prompt_cache",
    # 上下文压缩
    "model_context_window", "context_compression_ratio",
    "context_summary_threshold", "context_summary_target_chars",
    # Token 预算
    "session_token_limit", "daily_token_limit",
    # 子 Agent
    "sub_agent_max_depth", "sub_agent_max_tool_iterations",
    "sub_agent_max_recovery_attempts", "sub_agent_recursion_limit",
    # 工具
    "max_tool_calls_per_turn", "max_tool_output_chars",
    "tool_timeout_seconds", "tool_concurrency",
}

# 敏感字段：GET 时脱敏返回，PATCH 时原样存储
SENSITIVE: set[str] = {"anthropic_api_key", "anthropic_auth_token"}


def _mask(value: str | None) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 4 else "••••••••"


@router.get("/config")
async def get_config(
    _: Annotated[dict, Depends(require_auth)],
) -> dict[str, Any]:
    s = get_settings()
    result: dict[str, Any] = {}
    for key in EDITABLE:
        val = getattr(s, key, None)
        result[key] = _mask(val) if key in SENSITIVE and isinstance(val, str) and val else val
    # 附带计算属性（只读）
    result["context_compression_threshold"] = s.context_compression_threshold
    return result


class PatchBody(BaseModel):
    updates: dict[str, Any]


@router.patch("/config")
async def patch_config(
    body: PatchBody,
    _: Annotated[dict, Depends(require_auth)],
) -> dict[str, Any]:
    safe = {k: v for k, v in body.updates.items() if k in EDITABLE}
    if not safe:
        raise HTTPException(status_code=400, detail="无可更新的有效字段")
    s = get_settings()
    config_store.save(s.data_dir, safe)
    return {"status": "ok", "updated": sorted(safe.keys())}
