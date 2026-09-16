"""技能 CRUD —— 统一 EntityProvider 协议。

读写全部委托给 harness.providers.get_provider("skill")，与运行时（Skill /
上下文 L1 注入）共享同一 provider 单例与同一真源 settings.skills_dir/<name>/SKILL.md。
路由不再自持文件系统逻辑、目录默认值或 frontmatter 解析——写入即收敛为 CC 标准字段。
向量索引（Qdrant）在写/删后 best-effort 同步。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from harness.app.auth import require_auth
from harness.contracts.frontmatter import normalize_str_list, parse_bool, split_frontmatter
from harness.contracts.models import EntityFull, EntityMeta, SkillFull
from harness.providers import get_provider
from harness.routes._utils import resolve_rename, updated_entity_meta, validated_entity_name

router = APIRouter(prefix="/v1", tags=["skills"])


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _provider():
    return get_provider("skill")


def _invalidate_caches() -> None:
    """写入后失效上下文缓存（L1 清单注入）。provider.write/delete 已即时更新自身索引。"""
    try:
        from harness.core.context.builder import invalidate_context_cache

        invalidate_context_cache()
    except Exception:
        pass


def _sync_skill_vector(name: str, description: str) -> None:
    """同步 Skill 到向量库（best-effort，未配置 Qdrant 时静默跳过）。"""
    try:
        from harness.infra.vector import upsert_skill_embedding

        upsert_skill_embedding(f"skill:{name}", name, description)
    except Exception:
        pass


def _remove_skill_vector(name: str) -> None:
    """从向量库删除 Skill（best-effort）。"""
    try:
        from harness.infra.vector import delete_skill_embedding

        delete_skill_embedding(f"skill:{name}")
    except Exception:
        pass


def _skill_dict(full: EntityFull) -> dict:
    """SkillFull → API 响应（CC 标准字段）。"""
    return {
        "id": full.meta.name,
        "name": full.meta.name,
        "description": full.meta.description,
        "content": full.content,
        "model": full.model or "",
        "allowed_tools": getattr(full, "allowed_tools", []),
        "argument_hint": getattr(full, "argument_hint", "") or "",
        "disable_model_invocation": full.meta.disable_model_invocation,
        "user_invocable": full.meta.user_invocable,
    }


def _skill_from_fm(fm: dict, body: str) -> SkillFull:
    """frontmatter dict + 正文 → SkillFull。"""
    return SkillFull(
        meta=EntityMeta(
            name=(fm.get("name") or "").strip(),
            description=fm.get("description", "") or "",
            disable_model_invocation=parse_bool(fm.get("disable-model-invocation")),
            user_invocable=parse_bool(fm.get("user-invocable"), True),
        ),
        content=body.strip(),
        model=(fm.get("model") or None),
        allowed_tools=normalize_str_list(fm.get("allowed-tools")),
        argument_hint=(fm.get("argument-hint") or None),
    )


# ═══════════════════════════════════════════════════════════
# Pydantic
# ═══════════════════════════════════════════════════════════


class RegisterSkillRequest(BaseModel):
    md: str


class SkillPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    allowed_tools: list[str] | None = None
    model: str | None = None
    argument_hint: str | None = None


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════


@router.get("/skills")
async def list_skills(_: Annotated[dict, Depends(require_auth)]) -> list[dict]:
    p = _provider()
    p.reload()  # 管理端读：重扫磁盘保证列表最新
    out: list[dict] = []
    for name in p.all_names():
        full = p.get(name)
        if full is not None:
            out.append(_skill_dict(full))
    return out


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    full = _provider().get(skill_id)
    if full is None:
        raise HTTPException(404, "技能不存在")
    return _skill_dict(full)


@router.post("/skills/register", status_code=201)
async def register_skill(req: RegisterSkillRequest, _: Annotated[dict, Depends(require_auth)]) -> dict:
    fm, body = split_frontmatter(req.md)
    name = (fm.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "frontmatter 缺少 name 字段")
    name = validated_entity_name(name)
    full = _skill_from_fm(fm, body)
    _provider().write(name, full)
    _invalidate_caches()
    _sync_skill_vector(name, full.meta.description)
    return _skill_dict(full)


@router.patch("/skills/{skill_id}")
async def update_skill(skill_id: str, patch: SkillPatch, _: Annotated[dict, Depends(require_auth)]) -> dict:
    p = _provider()
    cur = p.get(skill_id)
    if cur is None:
        raise HTTPException(404, "技能不存在")

    new_id, rename = resolve_rename(p, skill_id, patch.name, "技能")

    new_full = SkillFull(
        meta=updated_entity_meta(cur, new_id, patch.description),
        content=patch.content if patch.content is not None else cur.content,
        model=(patch.model or None) if patch.model is not None else cur.model,
        allowed_tools=(
            patch.allowed_tools
            if patch.allowed_tools is not None
            else getattr(cur, "allowed_tools", [])
        ),
        argument_hint=(
            patch.argument_hint
            if patch.argument_hint is not None
            else getattr(cur, "argument_hint", None)
        ),
    )

    p.write(new_id, new_full)
    if rename:
        p.delete(skill_id)
        _remove_skill_vector(skill_id)  # 旧名 embedding 一并清，避免改名后 Qdrant 残留
    _invalidate_caches()
    _sync_skill_vector(new_id, new_full.meta.description)
    return _skill_dict(new_full)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, _: Annotated[dict, Depends(require_auth)]) -> None:
    if not _provider().delete(skill_id):
        raise HTTPException(404, "技能不存在")
    _remove_skill_vector(skill_id)
    _invalidate_caches()


@router.get("/skills/{skill_id}/deps")
async def skill_dep_tree(skill_id: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    if not _provider().has(skill_id):
        raise HTTPException(404, "技能不存在")
    return {"name": skill_id, "tree": ""}


@router.post("/skills/reindex")
async def reindex_skills(_: Annotated[dict, Depends(require_auth)]) -> dict:
    """重建所有 skill 的 embedding 索引。"""
    from harness.infra.vector import search_skills_semantic

    p = _provider()
    p.reload()
    count = 0
    for name in p.all_names():
        full = p.get(name)
        if full is None:
            continue
        _sync_skill_vector(name, full.meta.description)
        count += 1

    verified = len(search_skills_semantic("", k=count)) if count else 0
    return {"reindexed": count, "verified": verified}
