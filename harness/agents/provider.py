"""AgentProvider —— 文件系统 Agent 加载器（实现 EntityProvider）。

数据源: {VANTA_ROOT}/workspace/agents/<name>/AGENT.md
"""

from __future__ import annotations

import os
from pathlib import Path

from harness.contracts.base import BaseFileProvider
from harness.contracts.frontmatter import normalize_str_list
from harness.contracts.models import AgentFull, EntityFull, EntityMeta


def _agents_root() -> Path:
    vanta_root = os.getenv("VANTA_ROOT", str(Path.home() / "Vanta"))
    return Path(vanta_root) / "workspace" / "agents"


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
            path=path,
            tools=normalize_str_list(fm.get("tools")),
        )
