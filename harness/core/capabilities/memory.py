"""长期记忆封装：基于 infra.vector 的领域适配层。

- remember(): 写入一条用户/助手记忆
- recall(): 检索相关记忆
- _merge_memories(): 去重合并多路召回的记忆文本
- list_for_session(): 列出指定会话的所有记忆
- clear_for_session(): 删除指定会话的所有记忆
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from harness.infra import vector
from harness.infra.logging import log


def remember(
    text: str,
    *,
    session_id: str | None = None,
    role: str = "user",
) -> str:
    text = text.strip()
    if not text:
        return ""
    mid = vector.add_memory(text, session_id=session_id, role=role)
    log.info("memory.remember", id=mid, role=role, len=len(text))
    return mid


def recall_with_meta(query: str, *, k: int = 5) -> list[dict[str, Any]]:
    """检索并返回完整 dict（含 metadata、distance），供 UI 使用。"""
    if not query.strip():
        return []
    return vector.search_memory(query, k=k)


def _time_decay(created_at_iso: str) -> float:
    """返回时效性权重 [0, 1]。公式：1 / (1 + hours_ago / 24)。

    - 1小时前：0.96
    - 1天前：0.5
    - 7天前：0.13
    """
    try:
        dt = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        hours_ago = (datetime.now(UTC) - dt).total_seconds() / 3600
        return 1.0 / (1.0 + hours_ago / 24.0)
    except Exception:  # noqa: BLE001
        return 1.0  # 解析失败时不衰减


# 去近重复：候选与已选记忆余弦 > 此值即视为近重复、跳过。
# 实测近重复对(同段自我介绍两种问法)约 0.92，Qwen3 嵌入对近乎相同文本也只给 ~0.92，
# 故取 0.90（留余量；正常不同记忆一般 <0.88）。库变大后可再校准，必要时提为可配置。
_DIVERSITY_SIM_THRESHOLD = 0.90


def _cosine(a: list[float], b: list[float]) -> float:
    """两向量余弦相似度（纯 Python；召回候选量很小，无需引 numpy）。"""
    dot = na = nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


def recall_as_context(query: str, *, k: int = 5) -> str:
    """召回相关记忆，按 相似度×时效 排序 + 近重复抑制（多样性）后返回 top-k。

    自动捕获会把相似 Q&A 反复入库（近重复），纯相关性 top-k 会让几条近乎一样的记忆
    挤占名额。故相关性排序后做贪心去近重复：跳过与已选记忆余弦 > 阈值 的候选，用
    存储向量（search_memory with_vectors）算余弦，不额外调 embedding。
    """
    if not query.strip():
        return ""
    try:
        # 多取 2x 候选（连向量），加权 + 去近重复后截取 top-k
        raw = vector.search_memory(query, k=k * 2, with_vectors=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("memory.recall_failed", exc=str(exc))
        return ""

    if not raw:
        return ""

    # 相关性 = 相似度（1 - cosine_distance）× 时效性
    scored: list[tuple[float, str, list[float] | None]] = []
    for r in raw:
        similarity = max(0.0, 1.0 - r.get("distance", 1.0))
        decay = _time_decay(r.get("metadata", {}).get("created_at", ""))
        scored.append((similarity * decay, r["text"], r.get("vector")))
    scored.sort(key=lambda x: x[0], reverse=True)

    # 贪心去近重复：按相关性降序选取，跳过与已选余弦 > 阈值 的近重复候选
    top_items: list[str] = []
    sel_vecs: list[list[float]] = []
    for _, text, vec in scored:
        if len(top_items) >= k:
            break
        if vec and any(_cosine(vec, sv) > _DIVERSITY_SIM_THRESHOLD for sv in sel_vecs):
            continue
        top_items.append(text)
        if vec:
            sel_vecs.append(vec)

    lines = ["以下是与当前问题可能相关的过往记忆（仅作参考，不一定准确）："]
    for i, t in enumerate(top_items, 1):
        snippet = t.replace("\n", " ")[:200]
        lines.append(f"{i}. {snippet}")
    return "\n".join(lines)


def _merge_memories(raw_results: list[str], top_k: int) -> str:
    """Deduplicate and concatenate recalled memory lines."""
    seen: set[str] = set()
    merged_lines: list[str] = []
    for block in raw_results:
        if not block:
            continue
        for line in block.splitlines():
            if line and line not in seen:
                seen.add(line)
                merged_lines.append(line)
    max_lines = top_k * 5
    return "\n".join(merged_lines[:max_lines]) if merged_lines else ""


def list_for_session(session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return vector.list_memories(session_id=session_id, limit=limit)


def clear_for_session(session_id: str) -> int:
    n = vector.delete_by_session(session_id)
    log.info("memory.clear_session", session_id=session_id, deleted=n)
    return n
