"""路由层共享工具函数。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from harness.infra.logging import log


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """解析 markdown frontmatter，返回 (dict, body)。支持块标量/列表。"""
    # 先处理空 frontmatter（两个 --- 紧挨着）
    m = re.match(r"^---\r?\n---\r?\n?([\s\S]*)$", text)
    if m:
        return {}, m.group(1).strip()

    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$", text)
    if not m:
        return {}, text.strip()

    raw, body = m.group(1), m.group(2).strip()
    fm: dict[str, Any] = {}
    lines = raw.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        kv = re.match(r"^(\S.*?):\s*(.*)", line)
        if not kv:
            i += 1
            continue
        key, val = kv.group(1).strip(), kv.group(2).strip()

        if val in ("|", ">"):
            block: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                block.append(lines[i].lstrip())
                i += 1
            fm[key] = "\n".join(block).strip()
            continue

        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
            fm[key] = items
            i += 1
            continue

        if not val:
            block = []
            i += 1
            while i < len(lines) and re.match(r"^\s+-\s+", lines[i]):
                block.append(re.sub(r"^\s+-\s+", "", lines[i]).strip())
                i += 1
            fm[key] = block if block else ""
            continue

        fm[key] = val
        i += 1

    return fm, body


def parse_tools(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [t.strip() for t in re.split(r"[,\s]+", str(raw)) if t.strip()]


def extract_h1(content: str) -> str:
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


# ─── 序列化 ──────────────────────────────────────────────────────────
def knowledge_to_dict(r: Any) -> dict:
    return {
        "id":       r.id,
        "name":     r.name,
        "title":    r.title,
        "category": r.category,
        "content":  r.content,
        "tags":     json.loads(r.tags),
    }


def container_to_dict(r: Any, *, managed: bool = True, status: str | None = None) -> dict:
    """ContainerRecord → 前端 Container 形状。managed=本 App 建的（可操作生命周期）；
    status 传入时用 live daemon 状态覆盖库中的静态状态。"""
    return {
        "id":           r.id,
        "name":         r.name,
        "image":        r.image,
        "status":       status or r.status,
        "ports":        json.loads(r.ports) if r.ports else [],
        "env_vars":     json.loads(r.env_vars) if r.env_vars else [],
        "container_id": r.container_id,
        "managed":      managed,
        "created_at":   r.created_at.isoformat() if r.created_at else None,
        "updated_at":   r.updated_at.isoformat() if r.updated_at else None,
    }


def artifact_to_dict(r: Any) -> dict:
    """看板 artifact → 前端形状。secret 类不回明文正文（只留 vault_ref，见 BLACKBOARD P3）。"""
    return {
        "id":            r.id,
        "engagement_id": r.engagement_id,
        "producer":      r.producer,
        "kind":          r.kind,
        "sensitivity":   r.sensitivity,
        "title":         r.title,
        "content":       "" if r.sensitivity == "secret" else r.evidence,   # 甲：evidence 即正文
        "tags":          json.loads(r.tags) if r.tags else [],
        "vault_ref":     r.vault_ref,
        "severity":      r.severity,     # 仅 kind=finding 有意义
        "status":        r.status,
        "created_at":    r.created_at.isoformat() if r.created_at else None,
    }


# ─── get-or-404 ──────────────────────────────────────────────────────

async def get_or_404(db: AsyncSession, model: Any, pk: str, detail: str) -> Any:
    """db.get(model, pk)，未找到则抛出 404。"""
    rec = await db.get(model, pk)
    if not rec:
        raise HTTPException(404, detail)
    return rec


# ─── patch 应用 ──────────────────────────────────────────────────────

def apply_patch(record: Any, patch: Any, exclude: set[str] | None = None) -> None:
    """将 patch 中非 None 的字段赋值到 record，跳过 exclude 中的字段。"""
    skip = exclude or set()
    for field, value in patch.model_dump(exclude_unset=True).items():
        if field in skip:
            continue
        if value is not None:
            setattr(record, field, value)


# ─── 目录扫描注册 ────────────────────────────────────────────────────

async def scan_and_register(
    directory: Any,
    glob_pattern: str,
    register_func: Any,
    auth: Any,
    *,
    recursive: bool = False,
    preprocess: Any = None,
) -> dict[str, int]:
    """扫描目录并批量注册，返回 {"registered": int, "skipped": int}。

    preprocess: 可选的 async callable(md_file, md_text) -> str | None，
                用于在调用 register_func 前对文本做预处理。
                返回 None 表示跳过该文件。
    """
    registered, skipped = 0, 0
    glob_fn = directory.rglob if recursive else directory.glob
    for md_file in sorted(glob_fn(glob_pattern)):
        try:
            md_text = md_file.read_text(encoding="utf-8")
            if preprocess is not None:
                md_text = await preprocess(md_file, md_text)
                if md_text is None:
                    skipped += 1
                    continue
            await register_func(md_text, auth)
            registered += 1
        except Exception as e:  # noqa: BLE001
            log.warning("scan_and_register.skipped", file=str(md_file), error=str(e)[:120])
            skipped += 1
    return {"registered": registered, "skipped": skipped}


# ─── 缓存失效 ────────────────────────────────────────────────────────

def invalidate_entity_caches() -> None:
    """统一缓存失效。"""
    from harness.core.context.builder import invalidate_context_cache
    invalidate_context_cache()
