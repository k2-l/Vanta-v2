"""技能 CRUD — 纯文件系统，Claude Code 格式。

数据源: {VANTA_ROOT}/workspace/skills/*/SKILL.md
无 DB 依赖。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from harness.app.auth import require_auth

router = APIRouter(prefix="/v1", tags=["skills"])

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


# ═══════════════════════════════════════════════════════════
# 文件系统辅助
# ═══════════════════════════════════════════════════════════


def _skills_root() -> Path:
    vanta_root = os.getenv("VANTA_ROOT", str(Path.home() / "Vanta"))
    d = Path(vanta_root) / "workspace" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _skill_dir(name: str) -> Path:
    return _skills_root() / name


def _skill_md_path(name: str) -> Path:
    return _skill_dir(name) / "SKILL.md"


def _parse_skill_md(raw: str) -> tuple[dict, str]:
    """解析 YAML front matter，返回 (meta, body)"""
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw

    import yaml

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}

    return meta, raw[match.end() :]


def _read_skill(name: str) -> tuple[dict, str] | None:
    """读取并解析 SKILL.md，返回 (meta, body)；不存在返回 None"""
    md_path = _skill_md_path(name)
    if not md_path.is_file():
        return None
    raw = md_path.read_text(encoding="utf-8")
    return _parse_skill_md(raw)


def _write_skill(name: str, meta: dict, body: str) -> None:
    """写入 SKILL.md"""
    skill_dir = _skill_dir(name)
    skill_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for key in ["name", "description", "model", "version", "effort", "context"]:
        if key in meta and meta[key]:
            lines.append(f"{key}: {meta[key]}")
    if "argument-hint" in meta and meta["argument-hint"]:
        lines.append(f"argument-hint: {meta['argument-hint']}")
    if "allowed-tools" in meta and meta["allowed-tools"]:
        lines.append("allowed-tools:")
        for t in meta["allowed-tools"]:
            lines.append(f"  - {t}")
    if "triggers" in meta and meta["triggers"]:
        lines.append("triggers:")
        for t in meta["triggers"]:
            lines.append(f"  - {t}")

    content = "---\n" + "\n".join(lines) + "\n---\n" + body
    _skill_md_path(name).write_text(content, encoding="utf-8")


def _delete_skill_dir(name: str) -> None:
    """删除整个 Skill 目录"""
    skill_dir = _skill_dir(name)
    if skill_dir.is_dir():
        shutil.rmtree(skill_dir)


def _list_skills() -> list[dict]:
    """扫描所有 Skill 目录，返回 L1 信息列表"""
    root = _skills_root()
    skills = []
    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        parsed = _read_skill(name)
        if parsed is None:
            continue
        meta, _body = parsed
        triggers = meta.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        skills.append(
            {
                "id": name,
                "name": name,
                "description": meta.get("description", ""),
                "model": meta.get("model", ""),
                "allowed_tools": meta.get("allowed-tools", []),
                "triggers": triggers,
                "effort": meta.get("effort", ""),
                "context": meta.get("context", ""),
            }
        )
    return skills


def _invalidate_caches() -> None:
    try:
        from harness.core.context.builder import invalidate_context_cache

        invalidate_context_cache()
    except Exception:
        pass
    try:
        from harness.skills.loader import invalidate_entries_cache

        invalidate_entries_cache()
    except Exception:
        pass


def _sync_skill_vector(name: str, description: str) -> None:
    """同步 Skill 到向量库"""
    try:
        from harness.infra.vector import upsert_skill_embedding

        upsert_skill_embedding(f"skill:{name}", name, description)
    except Exception:
        pass


def _remove_skill_vector(name: str) -> None:
    """从向量库删除 Skill"""
    try:
        from harness.infra.vector import delete_skill_embedding

        delete_skill_embedding(f"skill:{name}")
    except Exception:
        pass


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
    triggers: list[str] | None = None
    model: str | None = None
    effort: str | None = None
    context: str | None = None
    argument_hint: str | None = None


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════


@router.get("/skills")
async def list_skills(_: dict = Depends(require_auth)) -> list[dict]:
    return _list_skills()


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, _: dict = Depends(require_auth)) -> dict:
    parsed = _read_skill(skill_id)
    if parsed is None:
        raise HTTPException(404, "技能不存在")
    meta, body = parsed
    triggers = meta.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [triggers]
    return {
        "id": skill_id,
        "name": meta.get("name", skill_id),
        "description": meta.get("description", ""),
        "content": body,
        "model": meta.get("model", ""),
        "allowed_tools": meta.get("allowed-tools", []),
        "triggers": triggers,
        "effort": meta.get("effort", ""),
        "context": meta.get("context", ""),
        "argument_hint": meta.get("argument-hint", ""),
        "version": meta.get("version", ""),
    }


@router.post("/skills/register", status_code=201)
async def register_skill(req: RegisterSkillRequest, _: dict = Depends(require_auth)) -> dict:
    meta, body = _parse_skill_md(req.md)
    name = (meta.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "frontmatter 缺少 name 字段")

    _write_skill(name, meta, body)
    _invalidate_caches()
    _sync_skill_vector(name, meta.get("description", ""))

    triggers = meta.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [triggers]
    return {
        "id": name,
        "name": name,
        "description": meta.get("description", ""),
        "content": body,
        "model": meta.get("model", ""),
        "allowed_tools": meta.get("allowed-tools", []),
        "triggers": triggers,
    }


@router.patch("/skills/{skill_id}")
async def update_skill(skill_id: str, patch: SkillPatch, _: dict = Depends(require_auth)) -> dict:
    parsed = _read_skill(skill_id)
    if parsed is None:
        raise HTTPException(404, "技能不存在")

    meta, body = parsed

    if patch.name is not None and patch.name != skill_id:
        _remove_skill_vector(skill_id)  # 旧名 embedding 一并清，避免改名后 Qdrant 残留
        _delete_skill_dir(skill_id)
        skill_id = patch.name

    if patch.description is not None:
        meta["description"] = patch.description
    if patch.content is not None:
        body = patch.content
    if patch.allowed_tools is not None:
        meta["allowed-tools"] = patch.allowed_tools
    if patch.triggers is not None:
        meta["triggers"] = patch.triggers
    if patch.model is not None:
        meta["model"] = patch.model
    if patch.effort is not None:
        meta["effort"] = patch.effort
    if patch.context is not None:
        meta["context"] = patch.context
    if patch.argument_hint is not None:
        meta["argument-hint"] = patch.argument_hint

    meta["name"] = skill_id  # frontmatter 名与目录名（=id=loader 索引键）对齐
    _write_skill(skill_id, meta, body)
    _invalidate_caches()
    _sync_skill_vector(skill_id, meta.get("description", ""))

    triggers = meta.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [triggers]
    return {
        "id": skill_id,
        "name": meta.get("name", skill_id),
        "description": meta.get("description", ""),
        "content": body,
        "model": meta.get("model", ""),
        "allowed_tools": meta.get("allowed-tools", []),
        "triggers": triggers,
    }


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, _: dict = Depends(require_auth)) -> None:
    if not _skill_dir(skill_id).is_dir():
        raise HTTPException(404, "技能不存在")
    _delete_skill_dir(skill_id)
    _remove_skill_vector(skill_id)
    _invalidate_caches()


@router.get("/skills/{skill_id}/deps")
async def skill_dep_tree(skill_id: str, _: dict = Depends(require_auth)) -> dict:
    parsed = _read_skill(skill_id)
    if parsed is None:
        raise HTTPException(404, "技能不存在")
    return {"name": skill_id, "tree": ""}


@router.post("/skills/reindex")
async def reindex_skills(_: dict = Depends(require_auth)) -> dict:
    """重建所有 skill 的 embedding 索引"""
    from harness.infra.vector import search_skills_semantic

    count = 0
    for skill in _list_skills():
        _sync_skill_vector(skill["name"], skill["description"])
        count += 1

    verified = len(search_skills_semantic("", k=count)) if count else 0
    return {"reindexed": count, "verified": verified}
