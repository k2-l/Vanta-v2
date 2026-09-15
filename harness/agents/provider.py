"""AgentProvider —— 文件系统 Agent 加载器（实现 EntityProvider）。

数据源: settings.agents_dir/<name>/AGENT.md
"""

from __future__ import annotations

from pathlib import Path

from harness.contracts.base import BaseFileProvider
from harness.contracts.frontmatter import normalize_str_list, parse_bool
from harness.contracts.models import (
    AgentFull,
    EntityFull,
    EntityMeta,
    normalize_provider_name,
)
from harness.infra.settings import get_settings


def _agents_root() -> Path:
    return Path(get_settings().agents_dir)


class AgentProvider(BaseFileProvider):
    kind = "agent"
    filename = "AGENT.md"
    l1_header = "# 可用 Agent 清单（Agent L1）"

    def __init__(self, root: str | Path | None = None):
        super().__init__(root or _agents_root())

    def _full(self, meta: EntityMeta, fm: dict, body: str, path: str) -> EntityFull:
        return AgentFull(
            meta=meta,
            content=body,
            model=fm.get("model"),
            provider=normalize_provider_name(fm.get("provider")),
            path=path,
            tools=normalize_str_list(fm.get("tools")),
            enable_critic=parse_bool(fm.get("enable_critic")),
        )
