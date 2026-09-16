"""GET /config  · PATCH /config — 运行时配置读写。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from harness.app.auth import require_auth
from harness.infra import config_store
from harness.infra.settings import Settings, get_settings

router = APIRouter(tags=["config"])

# 允许前端读写的字段白名单
EDITABLE: set[str] = {
    # 模型接口（凭据只通过环境变量配置）
    "anthropic_base_url", "openai_base_url",
    # 三档模型 + 各档 provider 覆盖（手工跨 provider 选择）
    "model_high", "model_mid", "model_low",
    "default_provider", "model_high_provider", "model_mid_provider", "model_low_provider",
    # 功能开关
    "enable_prompt_cache",
    # 上下文压缩
    "model_context_window", "context_compression_ratio",
    "context_summary_threshold", "context_summary_target_chars",
    # Token 预算
    "session_token_limit", "daily_token_limit",
    "main_agent_token_limit", "sub_agent_token_limit",
    # 子 Agent
    "sub_agent_max_depth", "sub_agent_max_tool_iterations",
    "sub_agent_max_recovery_attempts", "sub_agent_recursion_limit",
    "max_agent_delegations_per_agent", "max_agent_invocations_per_turn",
    # 工具
    "max_tool_calls_per_turn", "max_tool_output_chars",
    "tool_timeout_seconds", "tool_concurrency",
}

@router.get("/config")
async def get_config(
    _: Annotated[dict, Depends(require_auth)],
) -> dict[str, Any]:
    s = get_settings()
    result: dict[str, Any] = {}
    for key in EDITABLE:
        result[key] = getattr(s, key, None)
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
    try:
        Settings.model_validate({**s.model_dump(), **safe})
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(part) for part in err["loc"]),
                "message": err["msg"],
            }
            for err in exc.errors(include_input=False)
        ]
        raise HTTPException(
            status_code=422,
            detail={"message": "配置值无效", "errors": errors},
        ) from None
    config_store.save(s.data_dir, safe)
    return {"status": "ok", "updated": sorted(safe.keys())}
