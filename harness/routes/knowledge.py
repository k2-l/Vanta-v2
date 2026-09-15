"""知识库 CRUD — 存放 references/ 等知识文档。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from harness.app.auth import require_auth
from harness.infra.db import KnowledgeRecord, session_factory
from harness.infra.logging import log
from harness.infra.settings import get_settings
from harness.infra.vector import delete_knowledge as vec_delete
from harness.infra.vector import upsert_knowledge as vec_upsert
from harness.routes._utils import (
    apply_patch,
    extract_h1,
    get_or_404,
    knowledge_to_dict,
    parse_frontmatter,
)

router = APIRouter(prefix="/v1", tags=["knowledge"])


# ─── Pydantic ────────────────────────────────────────────────────────

class RegisterKnowledgeRequest(BaseModel):
    name: str
    title: str = ""
    category: str = ""
    content: str
    tags: list[str] = []


class RegisterKnowledgeMdRequest(BaseModel):
    md: str


class KnowledgePatch(BaseModel):
    name: str | None = None
    title: str | None = None
    category: str | None = None
    content: str | None = None
    tags: list[str] | None = None


# ─── 辅助 ────────────────────────────────────────────────────────────

def _name_id(name: str) -> str:
    """为知识名称生成稳定主键：短名称可读，长名称使用固定摘要。"""
    return name if len(name) <= 32 else hashlib.sha256(name.encode()).hexdigest()[:16]


def _knowledge_scan_files(root: str) -> tuple[Path, list[Path]] | None:
    base = Path(root).expanduser()
    if not base.is_dir():
        return None
    return base, sorted(base.rglob("*.md"))


def _read_knowledge_markdown(base: Path, markdown_file: Path) -> tuple[str, str, str]:
    content = markdown_file.read_text(encoding="utf-8")
    relative = markdown_file.relative_to(base)
    category = str(relative.parent).replace("\\", "/")
    return content, "" if category == "." else category, markdown_file.stem


# ─── 路由 ────────────────────────────────────────────────────────────

@router.get("/knowledge")
async def list_knowledge(_: Annotated[dict, Depends(require_auth)]) -> list[dict]:
    """列出数据库中的知识条目。"""
    async with session_factory()() as db:
        rows = (await db.execute(
            select(KnowledgeRecord).order_by(KnowledgeRecord.name)
        )).scalars().all()
        return [knowledge_to_dict(r) for r in rows]


@router.get("/knowledge/{kid}")
async def get_knowledge(kid: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    """按 id 取单个知识条目。"""
    async with session_factory()() as db:
        rec = await get_or_404(db, KnowledgeRecord, kid, "知识条目不存在")
        return knowledge_to_dict(rec)


@router.post("/knowledge/register", status_code=201)
async def register_knowledge(
    req: RegisterKnowledgeRequest,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    title = req.title or extract_h1(req.content) or req.name
    kid = _name_id(req.name)
    async with session_factory()() as db:
        rec = await db.get(KnowledgeRecord, kid)
        if rec:
            rec.name, rec.title, rec.category = req.name, title, req.category
            rec.content, rec.tags = req.content, json.dumps(req.tags)
        else:
            rec = KnowledgeRecord(
                id=kid, name=req.name, title=title,
                category=req.category, content=req.content, tags=json.dumps(req.tags),
            )
            db.add(rec)
        await db.commit()
        await db.refresh(rec)
        await asyncio.to_thread(
            vec_upsert,
            rec.id,
            rec.name,
            rec.title,
            rec.category,
            rec.content,
        )
        return knowledge_to_dict(rec)


@router.post("/knowledge/register-md", status_code=201)
async def register_knowledge_md(
    req: RegisterKnowledgeMdRequest,
    auth: Annotated[dict, Depends(require_auth)],
) -> dict:
    """从 Markdown 文本（含 frontmatter）注册知识条目，与 agent/skill 风格一致。"""
    fm, body = parse_frontmatter(req.md)
    name = (fm.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "frontmatter 缺少 name 字段")
    title_raw = fm.get("title") or ""
    tags_raw  = fm.get("tags") or []
    tags = tags_raw if isinstance(tags_raw, list) else [str(tags_raw)]
    return await register_knowledge(
        RegisterKnowledgeRequest(
            name=name,
            title=title_raw.strip() or extract_h1(body) or name,
            category=(fm.get("category") or "").strip(),
            content=body,
            tags=tags,
        ),
        auth,
    )


@router.patch("/knowledge/{kid}")
async def update_knowledge(
    kid: str,
    patch: KnowledgePatch,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    async with session_factory()() as db:
        rec = await get_or_404(db, KnowledgeRecord, kid, "知识条目不存在")
        # tags needs json.dumps
        apply_patch(rec, patch, exclude={"tags"})
        if patch.tags is not None:
            rec.tags = json.dumps(patch.tags)
        await db.commit()
        await db.refresh(rec)
        await asyncio.to_thread(
            vec_upsert,
            rec.id,
            rec.name,
            rec.title,
            rec.category,
            rec.content,
        )
        return knowledge_to_dict(rec)


@router.delete("/knowledge/{kid}", status_code=204)
async def delete_knowledge(
    kid: str,
    _: Annotated[dict, Depends(require_auth)],
) -> None:
    async with session_factory()() as db:
        await get_or_404(db, KnowledgeRecord, kid, "知识条目不存在")
        await db.execute(delete(KnowledgeRecord).where(KnowledgeRecord.id == kid))
        await db.commit()
    await asyncio.to_thread(vec_delete, kid)


@router.post("/knowledge/scan")
async def scan_knowledge(_: Annotated[dict, Depends(require_auth)]) -> dict:
    """扫描 HARNESS_REFERENCES_DIR 批量注册知识条目。"""
    s = get_settings()
    if not s.references_dir:
        raise HTTPException(400, "未配置 HARNESS_REFERENCES_DIR")
    scan = await asyncio.to_thread(_knowledge_scan_files, s.references_dir)
    if scan is None:
        raise HTTPException(400, f"目录不存在：{s.references_dir}")
    base, markdown_files = scan

    # knowledge scan 调用结构化的 RegisterKnowledgeRequest 而非原始 md 文本，
    # 且需要从相对路径提取 category，无法直接套用 scan_and_register 的 md-text 接口。
    registered, skipped = 0, 0
    for md_file in markdown_files:
        try:
            content, category, name = await asyncio.to_thread(
                _read_knowledge_markdown,
                base,
                md_file,
            )
            await register_knowledge(
                RegisterKnowledgeRequest(
                    name=name,
                    title=extract_h1(content) or name,
                    category=category,
                    content=content,
                ),
                _,
            )
            registered += 1
        except Exception as e:  # noqa: BLE001
            log.warning("knowledge.scan.skipped", file=str(md_file), error=str(e)[:120])
            skipped += 1

    return {"registered": registered, "skipped": skipped}


_REINDEX_BATCH = 100   # 每批处理条数，防止大 KB 一次性加载到内存


@router.post("/knowledge/reindex")
async def reindex_knowledge(_: Annotated[dict, Depends(require_auth)]) -> dict:
    """将所有现有 KB 文章重新写入 Qdrant 向量索引（backfill）。

    分批（每批 100 条）处理，失败条目记录 warning 日志。
    新部署或升级后调用一次，之后 register/delete 自动维护索引。
    """
    indexed, skipped, offset = 0, 0, 0

    while True:
        async with session_factory()() as db:
            batch = (await db.execute(
                select(KnowledgeRecord)
                .order_by(KnowledgeRecord.name)
                .offset(offset)
                .limit(_REINDEX_BATCH)
            )).scalars().all()

        if not batch:
            break

        for rec in batch:
            try:
                await asyncio.to_thread(
                    vec_upsert,
                    rec.id,
                    rec.name,
                    rec.title or rec.name,
                    rec.category or "",
                    rec.content or "",
                )
                indexed += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                log.warning("knowledge.reindex.failed",
                            id=rec.id, name=rec.name, exc=str(exc)[:120])

        offset += _REINDEX_BATCH

    log.info("knowledge.reindex.done", indexed=indexed, skipped=skipped)
    return {"indexed": indexed, "skipped": skipped}
