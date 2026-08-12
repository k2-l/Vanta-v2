from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import OrderedDict


class BaseRegistry(ABC):
    """Abstract base class shared by AgentRegistry and SkillRegistry.

    Provides the common L1 index structure (name → entry dict), count, names(),
    register(), load_compact(), load_from_db alias, and as_prompt_block().
    Subclasses override register() and load_compact() to handle their
    DB columns, and override as_prompt_block() to customise formatting.
    """

    def __init__(self) -> None:
        self._index: dict[str, dict] = {}

    @property
    def count(self) -> int:
        return len(self._index)

    def names(self) -> list[str]:
        return list(self._index.keys())

    @abstractmethod
    def register(self, name: str, description: str, **kwargs) -> None: ...

    @abstractmethod
    async def load_compact(self) -> None: ...

    # Backward-compat alias — concrete classes may override to re-alias
    @property
    def load_from_db(self):
        return self.load_compact

    @abstractmethod
    def as_prompt_block(self, name_filter: set[str] | None = None) -> str: ...


class LRUDict(OrderedDict):
    """OrderedDict with a maximum size that evicts the least-recently-used entry on overflow.

    Usage:
        cache = LRUDict(maxsize=200)
        cache[key] = value          # auto-evicts oldest entry when len > maxsize
        cache.move_to_end(key)      # mark key as most-recently-used
    """

    def __init__(self, maxsize: int, *args, **kwargs):
        self._maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)  # evict LRU entry


def _compact(text: str) -> str:
    """从 description 中提取 L1 紧凑描述：取第一句话。"""
    if not text:
        return ""
    for sep in ("\n", "。", ". "):
        idx = text.find(sep)
        if idx > 0:
            candidate = text[:idx]
            if candidate.strip():
                return candidate.strip()
    return text.strip()


def _parse_keywords(triggers_raw: str) -> list[str]:
    """从 triggers JSON 字符串解析为关键词列表。空/无效时返回 []。"""
    if not triggers_raw or triggers_raw == "[]":
        return []
    try:
        vals = json.loads(triggers_raw)
        if isinstance(vals, list):
            return [str(v).strip() for v in vals if v]
        return [str(triggers_raw).strip()]
    except (json.JSONDecodeError, ValueError):
        return []
