"""向量长期记忆 — Qdrant Cloud。

Embedding / ReRank 均走 Gitee AI 云端 API（OpenAI 兼容 embeddings + Jina/Cohere 风格 rerank）。
向量存储走 Qdrant Cloud。两者均云端唯一、硬失败：未配置 api_key/url 或调用出错时直接抛错，
不退回本地假向量/本地向量库、不静默吞错。

数据布局：
  collection = "memory" / "knowledge" / "skills"
  Qdrant point id 要求合法 UUID 或无符号整数，故 point id = uuid5(NAMESPACE, 原始 id)（确定性），
  原始 id（memory 用 uuid4 hex12；knowledge/skills 用调用方传入的 kb_id/skill_id）存入 payload，
  供 list_memories / search_* 按现有契约返回。
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from harness.infra.settings import get_settings

_EMBED_BATCH_SIZE = 32     # 防御性分批，避免单次请求 payload 过大
_HTTP_TIMEOUT = 30.0       # 秒

# point id 命名空间：原始 id（可能非 UUID）确定性映射到合法 UUID。
_POINT_NAMESPACE = uuid.UUID("a3f1c9e0-6b2d-4e5a-9c3f-1d2e3a4b5c6d")


def _point_id(original_id: str) -> str:
    """原始 id（任意字符串）→ 合法 UUID 字符串，确定性（同输入同输出，幂等 upsert/delete）。"""
    return str(uuid.uuid5(_POINT_NAMESPACE, original_id))


class _APIEmbedding:
    """Gitee AI embeddings API 客户端（OpenAI 兼容协议）。

    同时实现 langchain 风格（embed_query/embed_documents）与可调用（__call__）接口。
    云端唯一：出错直接 raise，不做本地兜底。
    """

    def __init__(self, model_name: str, base_url: str, api_key: str) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = httpx.post(
                f"{self._base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self._model_name, "input": texts},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise RuntimeError(
                f"Gitee AI embedding 调用失败 / Gitee AI embedding request failed: {e}"
            ) from e
        items = data.get("data", [])
        if not items:
            raise RuntimeError(
                "Gitee AI embedding 返回空结果 / Gitee AI embedding returned empty data: "
                f"{data!r}"
            )
        items.sort(key=lambda it: it.get("index", 0))
        return [it["embedding"] for it in items]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[i : i + _EMBED_BATCH_SIZE]
            results.extend(self._embed_batch(batch))
        return results

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self._embed(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self(input)

    def name(self) -> str:
        return self._model_name


class _APIReranker:
    """Gitee AI rerank API 客户端（Jina/Cohere 风格协议）。云端唯一，出错直接 raise。"""

    def __init__(self, model_name: str, base_url: str, api_key: str) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[dict[str, Any]]:
        """返回 [{"index": int, "relevance_score": float}, ...]，按 relevance_score 降序。"""
        try:
            resp = httpx.post(
                f"{self._base_url}/rerank",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "documents": documents,
                    "model": self._model_name,
                    "top_n": top_n,
                    "return_documents": False,
                },
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise RuntimeError(
                f"Gitee AI rerank 调用失败 / Gitee AI rerank request failed: {e}"
            ) from e
        results = data.get("results")
        if results is None:
            raise RuntimeError(
                f"Gitee AI rerank 返回格式异常 / Gitee AI rerank returned unexpected shape: {data!r}"
            )
        return results


_lock = threading.Lock()
_embedding_fn: Any = None
_reranker: Any = None


def _get_embedding_fn() -> Any:
    """构造 Gitee AI embedding 客户端（懒加载 + 单例缓存）。云端唯一，无本地兜底。"""
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn
    with _lock:
        if _embedding_fn is not None:
            return _embedding_fn
        s = get_settings()
        if not s.embedding_api_key:
            raise RuntimeError(
                "未配置 embedding_api_key：需在 data/config.toml 的 [embedding] 配置 api_key"
                "（云端唯一，无本地兜底）。\n"
                "embedding_api_key is not configured: set api_key under [embedding] in "
                "data/config.toml (cloud-only, no local fallback)."
            )
        _embedding_fn = _APIEmbedding(
            s.embedding_model, s.embedding_base_url, s.embedding_api_key
        )
        return _embedding_fn


def _rerank_active() -> bool:
    s = get_settings()
    return bool(s.rerank_enabled and s.embedding_model)


def _recall_n(k: int) -> int:
    """精排开启时把召回放大到 rerank_recall_n，否则就召回 k。"""
    return max(k, get_settings().rerank_recall_n) if _rerank_active() else k


def _get_reranker() -> Any:
    """构造 Gitee AI rerank 客户端（懒加载 + 单例缓存）。云端唯一，无本地兜底。"""
    global _reranker
    if _reranker is not None:
        return _reranker
    with _lock:
        if _reranker is not None:
            return _reranker
        s = get_settings()
        # rerank 凭据默认复用 embedding（同一 Gitee 端点）；[rerank] 显式填写则覆盖。
        api_key = s.rerank_api_key or s.embedding_api_key
        base_url = s.rerank_base_url or s.embedding_base_url
        if not api_key:
            raise RuntimeError(
                "未配置 rerank api_key：在 data/config.toml 的 [embedding] 或 [rerank] 配置 api_key"
                "（云端唯一，无本地兜底）。\n"
                "rerank api_key is not configured: set api_key under [embedding] or [rerank] "
                "in data/config.toml (cloud-only, no local fallback)."
            )
        _reranker = _APIReranker(s.rerank_model, base_url, api_key)
        return _reranker


def _rerank(query: str, items: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """云端 rerank 精排（items 需含 '_text'）返回 top-k。

    未启用（_rerank_active() 为 False）或 items 长度 ≤1 时直接短路返回向量序。
    启用后调用云端 API 出错时硬失败：异常向上抛，不做静默兜底。
    """
    if not _rerank_active() or len(items) <= 1:
        return items[:k]
    documents = [it.get("_text", "") for it in items]
    results = _get_reranker().rerank(query, documents, top_n=k)
    reranked: list[dict[str, Any]] = []
    for r in results:
        idx = r.get("index")
        if idx is None or not (0 <= idx < len(items)):
            continue
        it = items[idx]
        it["rerank_score"] = float(r.get("relevance_score", 0.0))
        reranked.append(it)
    reranked.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
    return reranked[:k]


# ─── Qdrant 客户端 ──────────────────────────────────────────────────────

_EMBED_DIM = 1024  # Qwen3-Embedding-8B 实测维度（非 4096）

# Qdrant 要求按 payload 字段过滤前先给该字段建索引。各 collection 需建索引的字段：
_PAYLOAD_INDEXES: dict[str, list[str]] = {
    "memory": ["session_id"],     # add_memory 去重 / search_memory / delete_by_session 过滤
    "knowledge": ["category"],    # search_knowledge_semantic 按分类过滤
}

_client: Any = None
_ensured_collections: set[str] = set()


def _get_client_locked() -> Any:
    """构造 Qdrant Cloud 客户端（懒加载 + 单例缓存）。调用方须已持有 _lock。"""
    global _client
    if _client is not None:
        return _client
    s = get_settings()
    if not s.qdrant_url or not s.qdrant_api_key:
        raise RuntimeError(
            "未配置 qdrant_url/qdrant_api_key：需在 data/config.toml 的 [qdrant] 配置 "
            "url 和 api_key（云端唯一，无本地兜底）。\n"
            "qdrant_url/qdrant_api_key is not configured: set url and api_key under "
            "[qdrant] in data/config.toml (cloud-only, no local fallback)."
        )
    from qdrant_client import QdrantClient

    _client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
    return _client


def _get_client() -> Any:
    """构造 Qdrant Cloud 客户端（懒加载 + 单例缓存）。云端唯一，缺凭据直接 raise。"""
    if _client is not None:
        return _client
    with _lock:
        return _get_client_locked()


def _ensure_collection(name: str = "memory") -> Any:
    """确保指定 collection 存在（幂等），返回 Qdrant client。结果按 name 缓存，线程安全。"""
    if name in _ensured_collections:
        return _get_client()
    with _lock:
        client = _get_client_locked()
        if name in _ensured_collections:
            return client

        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
            )
        # 为需要过滤的 payload 字段建 keyword 索引（幂等：已存在则忽略）。
        # Qdrant 不像 Chroma，未建索引的字段不能 filter，会 400。
        for field in _PAYLOAD_INDEXES.get(name, []):
            try:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:  # noqa: BLE001 — 索引已存在等情况忽略
                pass
        _ensured_collections.add(name)
        return client


def _session_filter(session_id: str) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))])


def _category_filter(category: str) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])


_DEDUP_SCORE_THRESHOLD = 0.85      # 余弦相似度 ≥ 此值视为重复（= 1 - 原 Chroma 距离阈值 0.15）
_MAX_MEMORIES_PER_SESSION = 50     # 每个 session 最多保留的记忆条数，超出时删最旧


def add_memory(
    text: str,
    *,
    session_id: str | None = None,
    role: str = "user",
    extra: dict[str, Any] | None = None,
) -> str:
    """写入一条记忆，返回 id。相似度过高（同 session 内近重复）时跳过写入。"""
    from qdrant_client.models import PointStruct

    client = _ensure_collection("memory")
    mid = uuid.uuid4().hex[:12]
    vec = _get_embedding_fn()([text])[0]

    # 同 session 内去重：仅在 session_id 非空时检查
    if session_id:
        try:
            hits = client.query_points(
                collection_name="memory",
                query=vec,
                query_filter=_session_filter(session_id),
                limit=1,
                with_payload=False,
            ).points
            if hits and hits[0].score >= _DEDUP_SCORE_THRESHOLD:
                from harness.infra.metrics import inc as _m_inc
                _m_inc("memory.dedup.skip")
                return mid  # 跳过写入，返回占位 id
        except Exception:  # noqa: BLE001
            pass  # query 失败则正常写入（去重是优化，非门控）

    payload: dict[str, Any] = {
        "id": mid,
        "text": text,
        "session_id": session_id or "",
        "role": role,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if extra:
        payload.update({k: str(v) for k, v in extra.items()})
    client.upsert(
        collection_name="memory",
        points=[PointStruct(id=_point_id(mid), vector=vec, payload=payload)],
    )

    # 容量管理：超出 per-session 上限时删最旧条目
    if session_id:
        try:
            # limit 稍大于上限，避免全量扫描历史债务
            scrolled, _ = client.scroll(
                collection_name="memory",
                scroll_filter=_session_filter(session_id),
                limit=_MAX_MEMORIES_PER_SESSION + 10,
                with_payload=["id", "created_at"],
            )
            if len(scrolled) > _MAX_MEMORIES_PER_SESSION:
                paired = sorted(
                    scrolled,
                    key=lambda p: p.payload.get("created_at", ""),
                )
                excess = len(scrolled) - _MAX_MEMORIES_PER_SESSION
                to_delete = [_point_id(p.payload["id"]) for p in paired[:excess]]
                client.delete(collection_name="memory", points_selector=to_delete)
        except Exception:  # noqa: BLE001
            pass  # 容量管理失败不阻断写入

    return mid


def search_memory(
    query: str,
    *,
    k: int = 5,
    session_id: str | None = None,
    with_vectors: bool = False,
) -> list[dict[str, Any]]:
    """语义召回 +（可选）ReRank 精排，返回 top-K。可选按 session 过滤。

    with_vectors=True 时每项附 "vector"（存储向量），供召回侧做多样性 / 近重复抑制，
    无需额外 embedding 调用。默认 False（UI 检索路径不取向量、省带宽）。
    """
    client = _ensure_collection("memory")
    vec = _get_embedding_fn()([query])[0]
    query_filter = _session_filter(session_id) if session_id else None
    hits = client.query_points(
        collection_name="memory",
        query=vec,
        query_filter=query_filter,
        limit=_recall_n(k),
        with_payload=True,
        with_vectors=with_vectors,
    ).points
    items = [
        {
            "text": h.payload.get("text", ""),
            "metadata": {
                k_: v_ for k_, v_ in h.payload.items() if k_ not in ("text", "id")
            },
            "distance": 1 - h.score,
            "_text": h.payload.get("text", ""),
            **({"vector": list(h.vector)} if with_vectors and h.vector is not None else {}),
        }
        for h in hits
    ]
    items = _rerank(query, items, k)
    for it in items:
        it.pop("_text", None)
    return items


def count() -> int:
    client = _ensure_collection("memory")
    return client.count(collection_name="memory", exact=True).count


def list_memories(
    *,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出记忆。可选按 session_id 过滤。"""
    client = _ensure_collection("memory")
    scroll_filter = _session_filter(session_id) if session_id else None
    scrolled, _ = client.scroll(
        collection_name="memory",
        scroll_filter=scroll_filter,
        limit=limit,
        with_payload=True,
    )
    out: list[dict[str, Any]] = []
    for p in scrolled:
        payload = dict(p.payload)
        text = payload.pop("text", "")
        out.append({"id": payload.pop("id", ""), "text": text, "metadata": payload})
    return out


def delete_by_session(session_id: str) -> int:
    """删除指定 session 的所有记忆，返回删除条数。"""
    client = _ensure_collection("memory")
    scrolled, _ = client.scroll(
        collection_name="memory",
        scroll_filter=_session_filter(session_id),
        limit=10_000,
        with_payload=False,
    )
    n = len(scrolled)
    if n:
        from qdrant_client.models import FilterSelector

        client.delete(
            collection_name="memory",
            points_selector=FilterSelector(filter=_session_filter(session_id)),
        )
    return n


def reset() -> None:
    """⚠ 测试用：清空集合。"""
    if _client is not None:
        for name in ("memory", "knowledge", "skills"):
            try:
                if _client.collection_exists(name):
                    _client.delete_collection(name)
            except Exception:  # noqa: BLE001
                pass
    _ensured_collections.clear()


# ─── Knowledge 语义搜索 collection ────────────────────────────────────

def upsert_knowledge(
    kb_id: str,
    name: str,
    title: str,
    category: str,
    content: str,
) -> None:
    """将知识文章写入/更新到向量索引。由 knowledge route 在 CRUD 时调用。"""
    from qdrant_client.models import PointStruct

    try:
        client = _ensure_collection("knowledge")
        doc = f"{name} {title}\n\n{content}"
        vec = _get_embedding_fn()([doc])[0]
        payload = {"id": kb_id, "name": name, "title": title, "category": category, "_doc": doc}
        client.upsert(
            collection_name="knowledge",
            points=[PointStruct(id=_point_id(kb_id), vector=vec, payload=payload)],
        )
    except Exception:  # noqa: BLE001
        pass  # 向量索引失败不阻断主流程


def delete_knowledge(kb_id: str) -> None:
    """从向量索引删除知识文章。"""
    try:
        _ensure_collection("knowledge").delete(
            collection_name="knowledge", points_selector=[_point_id(kb_id)]
        )
    except Exception:  # noqa: BLE001
        pass


def search_knowledge_semantic(
    query: str,
    *,
    k: int = 5,
    category: str = "",
) -> list[dict[str, Any]]:
    """语义搜索知识文章，返回 [{"id", "name", "title", "category", "distance"}]。

    若集合为空返回空列表，调用方应 fallback 到 SQL 搜索。
    """
    try:
        client = _ensure_collection("knowledge")
        vec = _get_embedding_fn()([query])[0]
        query_filter = _category_filter(category) if category else None
        hits = client.query_points(
            collection_name="knowledge",
            query=vec,
            query_filter=query_filter,
            limit=_recall_n(k),
            with_payload=True,
        ).points
    except Exception:  # noqa: BLE001
        return []
    items: list[dict[str, Any]] = []
    for h in hits:
        payload = h.payload
        items.append({
            "id":       payload.get("id", ""),
            "name":     payload.get("name", ""),
            "title":    payload.get("title", ""),
            "category": payload.get("category", ""),
            "distance": 1 - h.score,
            "_text":    payload.get("_doc", ""),
        })
    items = _rerank(query, items, k)
    for it in items:
        it.pop("_text", None)
    return items


def kb_collection_count() -> int:
    """知识库向量集合中的文章数（用于测试和监控）。"""
    try:
        client = _ensure_collection("knowledge")
        return client.count(collection_name="knowledge", exact=True).count
    except Exception:  # noqa: BLE001
        return 0


# ─── Skill 语义索引 collection ──────────────────────────────────────────

def upsert_skill_embedding(skill_id: str, name: str, description: str) -> None:
    """将 skill description 写入向量索引。由 skill route 在注册/更新时调用。"""
    from qdrant_client.models import PointStruct

    try:
        client = _ensure_collection("skills")
        doc = f"{name}: {description}"
        vec = _get_embedding_fn()([doc])[0]
        payload = {"id": skill_id, "name": name, "_doc": doc}
        client.upsert(
            collection_name="skills",
            points=[PointStruct(id=_point_id(skill_id), vector=vec, payload=payload)],
        )
    except Exception:  # noqa: BLE001
        pass


def delete_skill_embedding(skill_id: str) -> None:
    """从向量索引删除 skill。"""
    try:
        _ensure_collection("skills").delete(
            collection_name="skills", points_selector=[_point_id(skill_id)]
        )
    except Exception:  # noqa: BLE001
        pass


def search_skills_semantic(query: str, *, k: int = 5) -> list[dict[str, Any]]:
    """语义搜索技能，返回 top-K [{"name", "distance"}]。空集合返回 []。"""
    try:
        client = _ensure_collection("skills")
        vec = _get_embedding_fn()([query])[0]
        hits = client.query_points(
            collection_name="skills",
            query=vec,
            limit=_recall_n(k),
            with_payload=True,
        ).points
    except Exception:  # noqa: BLE001
        return []
    items: list[dict[str, Any]] = []
    for h in hits:
        payload = h.payload
        items.append({
            "name": payload.get("name", ""),
            "distance": 1 - h.score,
            "_text": payload.get("_doc", ""),
        })
    items = _rerank(query, items, k)
    for it in items:
        it.pop("_text", None)
    return items
