"""统一 Provider 入口（组合根 / 服务定位器）。

核心层与工具层通过 get_provider(kind) 取得 provider，只依赖 EntityProvider 协议，
不 import 具体实现——依赖倒置的落点。单例实例集中缓存在此，各 provider 模块不再自持单例。
"""

from __future__ import annotations

from harness.agents.provider import AgentProvider
from harness.contracts.base import BaseFileProvider
from harness.contracts.protocol import EntityProvider
from harness.skills.provider import SkillProvider

_CLASSES: dict[str, type[BaseFileProvider]] = {"agent": AgentProvider, "skill": SkillProvider}
_instances: dict[str, BaseFileProvider] = {}


def get_provider(kind: str) -> EntityProvider:
    if kind not in _instances:
        cls = _CLASSES.get(kind)
        if cls is None:
            raise ValueError(f"unknown provider kind: {kind!r}（仅 'agent' | 'skill'）")
        p = cls()
        p.reload()
        _instances[kind] = p
    return _instances[kind]


def reload_all() -> dict[str, int]:
    """重扫两域，返回各自条目数。CRUD 写入后可调用以失效缓存。"""
    return {kind: get_provider(kind).reload() for kind in _CLASSES}
