"""统一 Provider 入口（组合根 / 服务定位器）。

核心层与工具层通过 get_provider(kind) 取得 provider，只依赖 EntityProvider 协议，
不 import 具体实现——依赖倒置的落点。
"""

from __future__ import annotations

from harness.agents.provider import get_agent_provider
from harness.contracts.protocol import EntityProvider
from harness.skills.provider import get_skill_provider


def get_provider(kind: str) -> EntityProvider:
    if kind == "agent":
        return get_agent_provider()
    if kind == "skill":
        return get_skill_provider()
    raise ValueError(f"unknown provider kind: {kind!r}（仅 'agent' | 'skill'）")


def reload_all() -> dict[str, int]:
    """重扫两域，返回各自条目数。CRUD 写入后可调用以失效缓存。"""
    return {
        "agent": get_agent_provider().reload(),
        "skill": get_skill_provider().reload(),
    }
