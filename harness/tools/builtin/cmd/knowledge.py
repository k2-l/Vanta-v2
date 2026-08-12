"""知识库工具 — 从 PostgreSQL knowledge 表按需检索（语义搜索 + 取全文，合一为 knowledge）。

knowledge(query=...) 语义搜索相关文档列表（向量召回 + ReRank 精排）
knowledge(name=...)  获取指定文档完整内容
"""

from __future__ import annotations

import asyncio
from typing import Any

from harness.infra.logging import log
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register


@register
class KnowledgeTool(Tool):
    name = "knowledge"
    category = "knowledge"
    description = (
        "知识库检索。两种用法：\n"
        "- 传 query：语义搜索相关文档，返回 名称 + 分类 + 摘要 列表；\n"
        "- 传 name：获取指定文档的完整内容。\n"
        "通常先用 query 搜到目标文档名，再用 name 取全文。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "语义搜索关键词（如 SQL注入、JWT、反序列化）。传此参数=搜索模式。",
            },
            "name": {
                "type": "string",
                "description": "文档名（如 java-auditor、sqli-bypass）。传此参数=取完整内容模式。",
            },
            "category": {
                "type": "string",
                "description": "限定/精确分类（如 audit、audit/auth-logic），选填。",
                "default": "",
            },
            "top_k": {
                "type": "integer",
                "description": "搜索模式返回条数，默认 5。",
                "default": 5,
            },
        },
    }

    async def run(self, query: str = "", name: str = "", category: str = "", top_k: int = 5) -> ToolResult:
        if name:
            return await self._get(name, category)
        if query:
            return await self._search(query, category, top_k)
        return ToolResult.fail(
            error="knowledge 需要 query（语义搜索）或 name（取完整内容）之一",
            error_code="INVALID_ARGS",
        )

    async def _get(self, name: str, category: str) -> ToolResult:
        from sqlalchemy import select

        from harness.infra.db import KnowledgeRecord, session_factory

        try:
            async with session_factory()() as db:
                q = select(KnowledgeRecord).where(KnowledgeRecord.name == name)
                if category:
                    q = q.where(KnowledgeRecord.category == category)
                rec = (await db.execute(q.limit(1))).scalar_one_or_none()

            if rec is None:
                hint = f"（分类：{category}）" if category else ""
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"知识库中找不到文档：{name}{hint}，请先通过扫描导入。",
                )

            header = f"# {rec.title or rec.name}  [{rec.category}/{rec.name}]\n\n"
            return ToolResult(ok=True, output=header + rec.content)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=str(exc))

    async def _search(self, query: str, category: str, top_k: int) -> ToolResult:
        from sqlalchemy import or_, select

        from harness.infra.db import KnowledgeRecord, session_factory
        from harness.infra.vector import search_knowledge_semantic

        try:
            q_lower = query.lower()

            # ── 1. 语义搜索（Qdrant，向量召回 + ReRank）——集合非空则优先 ──
            semantic_hits = await asyncio.to_thread(
                search_knowledge_semantic, query, k=top_k * 2, category=category
            )

            rows: list = []
            used_semantic = False

            if semantic_hits:
                hit_ids = [h["id"] for h in semantic_hits[:top_k]]
                async with session_factory()() as db:
                    rows = (await db.execute(
                        select(KnowledgeRecord).where(KnowledgeRecord.id.in_(hit_ids))
                    )).scalars().all()
                if rows:
                    id_order = {kb_id: i for i, kb_id in enumerate(hit_ids)}
                    rows = sorted(rows, key=lambda r: id_order.get(r.id, 999))
                    used_semantic = True

            if not rows:
                # ── Fallback：SQL LIKE + Python 相关性排序 ─────────────────
                log.info("knowledge.fallback_to_sql", query=query[:80], semantic_hits=len(semantic_hits))
                async with session_factory()() as db:
                    q = select(KnowledgeRecord)
                    if category:
                        q = q.where(KnowledgeRecord.category.like(f"{category}%"))
                    pattern = f"%{query}%"
                    q = q.where(
                        or_(
                            KnowledgeRecord.name.ilike(pattern),
                            KnowledgeRecord.title.ilike(pattern),
                            KnowledgeRecord.category.ilike(pattern),
                            KnowledgeRecord.content.ilike(pattern),
                        )
                    ).limit(top_k * 3)
                    rows = (await db.execute(q)).scalars().all()

            if not rows:
                return ToolResult(
                    ok=True,
                    output=f"未找到与「{query}」相关的知识文档。请确认关键词或先导入相关知识。",
                )

            if used_semantic:
                ranked = list(rows)
            else:
                def _score(r: KnowledgeRecord) -> int:
                    score = 0
                    if q_lower in r.name.lower():
                        score += 4 + max(0, 10 - r.name.lower().index(q_lower))
                    if q_lower in (r.title or "").lower():
                        score += 3
                    if q_lower in (r.category or "").lower():
                        score += 2
                    content_head = r.content[:500].lower() if r.content else ""
                    content_full = r.content.lower() if r.content else ""
                    if q_lower in content_head:
                        score += 2
                    elif q_lower in content_full:
                        score += 1
                    return score
                ranked = sorted(rows, key=_score, reverse=True)[:top_k]

            lines = [f"找到 {len(ranked)} 条相关文档（按相关性排序）：\n"]
            for r in ranked:
                snippet = r.content[:150].replace("\n", " ")
                lines.append(
                    f"- **{r.name}** [{r.category}]\n"
                    f"  标题：{r.title or r.name}\n"
                    f"  摘要：{snippet}…\n"
                    f'  → 用 knowledge(name="{r.name}", category="{r.category}") 获取完整内容'
                )

            return ToolResult(ok=True, output="\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=str(exc))
