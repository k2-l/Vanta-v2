"""SkillProvider —— 文件系统 Skill 加载器（实现 EntityProvider）。

数据源: settings.skills_dir/<name>/SKILL.md
"""

from __future__ import annotations

from pathlib import Path

from harness.contracts.base import BaseFileProvider
from harness.contracts.frontmatter import normalize_str_list
from harness.contracts.models import EntityFull, EntityMeta, SkillFull
from harness.infra.settings import get_settings


def _skills_root() -> Path:
    return Path(get_settings().skills_dir)


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
