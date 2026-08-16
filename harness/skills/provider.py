"""SkillProvider —— 文件系统 Skill 加载器（实现 EntityProvider）。

数据源: {VANTA_ROOT}/workspace/skills/<name>/SKILL.md
"""

from __future__ import annotations

import os
from pathlib import Path

from harness.contracts.base import BaseFileProvider
from harness.contracts.frontmatter import normalize_str_list
from harness.contracts.models import EntityFull, EntityMeta, SkillFull


def _skills_root() -> Path:
    vanta_root = os.getenv("VANTA_ROOT", str(Path.home() / "Vanta"))
    return Path(vanta_root) / "workspace" / "skills"


class SkillProvider(BaseFileProvider):
    kind = "skill"
    filename = "SKILL.md"
    l1_header = "# 可用 Skill 清单（Skill L1）"

    def __init__(self, root: str | Path | None = None):
        super().__init__(root or _skills_root())

    def _full(self, meta: EntityMeta, fm: dict, body: str, path: str) -> EntityFull:
        return SkillFull(
            meta=meta,
            content=body,
            model=fm.get("model"),
            path=path,
            allowed_tools=normalize_str_list(fm.get("allowed-tools")),
            argument_hint=fm.get("argument-hint"),
        )


# ── 单例 ─────────────────────────────────────────────────────
_provider: SkillProvider | None = None


def get_skill_provider() -> SkillProvider:
    global _provider
    if _provider is None:
        _provider = SkillProvider()
        _provider.reload()
    return _provider


def reset_skill_provider() -> None:
    """测试用：清空单例。"""
    global _provider
    _provider = None
