"""workspace 文件 → DB 同步（端口 nexus services/indexer.go ScanKind + handlers/workspace.go）。

扫 `suite_dir/<kind>/*.md`，逐个 upsert 进 DB（复用各 kind 的 register 处理器），再 **prune** 掉
「库有、workspace 文件无」的记录（复用 delete 处理器，连带 file/vector/依赖级联一并清），最后失效 L1 缓存。
前端 KB 页的「从 workspace 同步」按钮走 `POST /v1/workspace/sync/knowledge`（P3 前端从 nexus 改指这里）。

⚠️ prune 是破坏性的：目录里没有对应文件的库行会被删（对齐 nexus 原行为）。故要求目录已配置且存在，
否则拒绝（不 prune），避免误配置把整类记录清空。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from harness.app.auth import require_auth
from harness.infra.db import AgentRecord, KnowledgeRecord, SkillRecord, session_factory
from harness.infra.logging import log
from harness.infra.settings import get_settings
from harness.routes._utils import extract_h1, invalidate_entity_caches, parse_frontmatter

router = APIRouter(prefix="/v1", tags=["workspace"])

_SYNC_KINDS = ("agents", "skills", "knowledge")


@router.post("/workspace/sync/{kind}")
async def sync_kind(kind: str, auth: dict = Depends(require_auth)) -> dict:
    """把 workspace/<kind>/*.md reconcile 进 DB（upsert + prune）。返回 {registered, skipped, pruned}。"""
    if kind not in _SYNC_KINDS:
        raise HTTPException(400, f"不支持的 kind：{kind}（仅 {', '.join(_SYNC_KINDS)}）")
    s = get_settings()
    if not s.suite_dir:
        raise HTTPException(400, "未配置 suite_dir")
    d = Path(s.suite_dir).expanduser() / kind
    if not d.is_dir():
        raise HTTPException(400, f"目录不存在：{d}")

    if kind == "agents":
        result = await _sync_agents(d, auth)
        invalidate_entity_caches("agent")
    elif kind == "skills":
        result = await _sync_skills(d, auth)
        invalidate_entity_caches("skill")
    else:
        result = await _sync_knowledge(d, auth)
        invalidate_entity_caches("agent")   # knowledge 无独立 entries 缓存，只需清 context 缓存
    return result


async def _sync_agents(d: Path, auth: dict) -> dict:
    from harness.routes.agents import RegisterAgentRequest, delete_agent, register_agent

    registered = skipped = 0
    seen: set[str] = set()
    for md in sorted(d.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(text)
            name = (fm.get("name") or "").strip()
            if not name:
                skipped += 1
                continue
            await register_agent(RegisterAgentRequest(md=text), auth)
            seen.add(name)
            registered += 1
        except Exception as e:  # noqa: BLE001
            log.warning("workspace.sync.agents.skipped", file=str(md), error=str(e)[:120])
            skipped += 1
    pruned = await _prune(AgentRecord, seen, delete_agent, auth)
    return {"registered": registered, "skipped": skipped, "pruned": pruned}


async def _sync_skills(d: Path, auth: dict) -> dict:
    from harness.routes.skills import RegisterSkillRequest, delete_skill, register_skill

    registered = skipped = 0
    seen: set[str] = set()
    for md in sorted(d.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(text)
            name = (fm.get("name") or "").strip()
            if not name:
                skipped += 1
                continue
            await register_skill(RegisterSkillRequest(md=text), auth)
            seen.add(name)
            registered += 1
        except Exception as e:  # noqa: BLE001
            log.warning("workspace.sync.skills.skipped", file=str(md), error=str(e)[:120])
            skipped += 1
    pruned = await _prune(SkillRecord, seen, delete_skill, auth)
    return {"registered": registered, "skipped": skipped, "pruned": pruned}


async def _sync_knowledge(d: Path, auth: dict) -> dict:
    from harness.routes.knowledge import (
        RegisterKnowledgeRequest,
        delete_knowledge,
        register_knowledge,
    )

    registered = skipped = 0
    seen: set[str] = set()
    for md in sorted(d.glob("*.md")):
        try:
            content = md.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)
            name = (fm.get("name") or md.stem).strip()
            tags = fm.get("tags") or []
            if not isinstance(tags, list):
                tags = [str(tags)]
            await register_knowledge(
                RegisterKnowledgeRequest(
                    name=name,
                    title=(fm.get("title") or "").strip() or extract_h1(body) or name,
                    category=(fm.get("category") or "").strip(),
                    content=body,
                    tags=tags,
                ),
                auth,
            )
            seen.add(name)
            registered += 1
        except Exception as e:  # noqa: BLE001
            log.warning("workspace.sync.knowledge.skipped", file=str(md), error=str(e)[:120])
            skipped += 1
    pruned = await _prune(KnowledgeRecord, seen, delete_knowledge, auth)
    return {"registered": registered, "skipped": skipped, "pruned": pruned}


async def _prune(model: type, seen_names: set[str], delete_handler, auth: dict) -> int:
    """删掉 name 不在 seen_names 里的库行（复用各 kind 的 delete 处理器，级联 file/vector/依赖）。"""
    async with session_factory()() as db:
        rows = (await db.execute(select(model))).scalars().all()
        orphans = [r.id for r in rows if r.name not in seen_names]
    for rid in orphans:
        try:
            await delete_handler(rid, auth)
        except Exception as e:  # noqa: BLE001
            log.warning("workspace.sync.prune.failed", model=model.__name__, id=rid, error=str(e)[:120])
    return len(orphans)
