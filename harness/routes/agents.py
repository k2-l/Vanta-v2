"""Agent CRUD —— 统一 EntityProvider 协议。

读写全部委托给 harness.providers.get_provider("agent")，与运行时（Agent /
上下文 L1 注入）共享同一 provider 单例与同一真源 settings.agents_dir/<name>/AGENT.md。
路由不再自持文件系统逻辑、目录默认值或 frontmatter 解析——写入即收敛为 CC 标准字段。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from harness.app.auth import require_auth
from harness.contracts.frontmatter import normalize_str_list, parse_bool, split_frontmatter
from harness.contracts.models import (
    AgentFull,
    EntityFull,
    EntityMeta,
    ProviderName,
    normalize_provider_name,
)
from harness.providers import get_provider
from harness.routes._utils import resolve_rename, validated_entity_name

router = APIRouter(prefix="/v1", tags=["agents"])


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _provider():
    return get_provider("agent")


def _invalidate_caches() -> None:
    """写入后失效上下文缓存（L1 清单注入）。provider.write/delete 已即时更新自身索引。"""
    try:
        from harness.core.context.builder import invalidate_context_cache

        invalidate_context_cache()
    except Exception:
        pass


def _agent_dict(full: EntityFull) -> dict:
    """AgentFull → API 响应（CC 标准字段）。"""
    return {
        "id": full.meta.name,
        "name": full.meta.name,
        "description": full.meta.description,
        "content": full.content,
        "model": full.model or "",
        "provider": full.provider,
        "tools": getattr(full, "tools", []),
        "enable_critic": getattr(full, "enable_critic", False),
        "disable_model_invocation": full.meta.disable_model_invocation,
        "user_invocable": full.meta.user_invocable,
    }


def _agent_from_fm(fm: dict, body: str) -> AgentFull:
    """frontmatter dict + 正文 → AgentFull（provider 归一化可能抛 ValueError）。"""
    return AgentFull(
        meta=EntityMeta(
            name=(fm.get("name") or "").strip(),
            description=fm.get("description", "") or "",
            disable_model_invocation=parse_bool(fm.get("disable-model-invocation")),
            user_invocable=parse_bool(fm.get("user-invocable"), True),
        ),
        content=body.strip(),
        model=(fm.get("model") or None),
        provider=normalize_provider_name(fm.get("provider")),
        tools=normalize_str_list(fm.get("tools")),
        enable_critic=parse_bool(fm.get("enable_critic")),
    )


# ═══════════════════════════════════════════════════════════
# Pydantic
# ═══════════════════════════════════════════════════════════


class RegisterAgentRequest(BaseModel):
    md: str


class AgentPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    tools: list[str] | None = None
    model: str | None = None
    provider: ProviderName | None = None
    enable_critic: bool | None = None
    disable_model_invocation: bool | None = None
    user_invocable: bool | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> ProviderName | None:
        return normalize_provider_name(value)


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════


@router.get("/agents")
async def list_agents(_: Annotated[dict, Depends(require_auth)]) -> list[dict]:
    p = _provider()
    p.reload()  # 管理端读：重扫磁盘保证列表最新
    out: list[dict] = []
    for name in p.all_names():
        full = p.get(name)
        if full is not None:
            out.append(_agent_dict(full))
    return out


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    full = _provider().get(agent_id)
    if full is None:
        raise HTTPException(404, "Agent 不存在")
    return _agent_dict(full)


@router.post("/agents/register", status_code=201)
async def register_agent(
    req: RegisterAgentRequest,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    fm, body = split_frontmatter(req.md)
    name = (fm.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "frontmatter 缺少 name 字段")
    name = validated_entity_name(name)
    try:
        full = _agent_from_fm(fm, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    provider = _provider()
    if provider.has(name):
        raise HTTPException(409, f"Agent 已存在：{name}")
    provider.write(name, full)
    _invalidate_caches()
    return _agent_dict(full)


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    patch: AgentPatch,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    p = _provider()
    cur = p.get(agent_id)
    if cur is None:
        raise HTTPException(404, "Agent 不存在")

    new_id, rename = resolve_rename(p, agent_id, patch.name, "Agent")

    new_full = AgentFull(
        meta=EntityMeta(
            name=new_id,
            description=(
                patch.description
                if patch.description is not None
                else cur.meta.description
            ),
            disable_model_invocation=(
                patch.disable_model_invocation
                if patch.disable_model_invocation is not None
                else cur.meta.disable_model_invocation
            ),
            user_invocable=(
                patch.user_invocable
                if patch.user_invocable is not None
                else cur.meta.user_invocable
            ),
        ),
        content=patch.content if patch.content is not None else cur.content,
        model=(patch.model or None) if patch.model is not None else cur.model,
        provider=patch.provider if "provider" in patch.model_fields_set else cur.provider,
        tools=patch.tools if patch.tools is not None else getattr(cur, "tools", []),
        enable_critic=(
            patch.enable_critic
            if patch.enable_critic is not None
            else getattr(cur, "enable_critic", False)
        ),
    )

    p.write(new_id, new_full)
    if rename:
        p.delete(agent_id)
    _invalidate_caches()
    return _agent_dict(new_full)


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, _: Annotated[dict, Depends(require_auth)]) -> None:
    if not _provider().delete(agent_id):
        raise HTTPException(404, "Agent 不存在")
    _invalidate_caches()


@router.get("/agents/{agent_id}/deps")
async def agent_dep_tree(agent_id: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    """文件系统模式下无依赖树概念，返回空。"""
    if not _provider().has(agent_id):
        raise HTTPException(404, "Agent 不存在")
    return {"name": agent_id, "tree": ""}
