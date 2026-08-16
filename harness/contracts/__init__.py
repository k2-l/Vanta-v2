"""L0 契约层（零依赖）：实体统一模型 + 协议 + 通用文件加载器。

领域层（agents / skills）与核心层都只向下依赖本包，彼此不互相 import——切断循环。
"""

from harness.contracts.base import BaseFileProvider
from harness.contracts.frontmatter import iter_entity_dirs, split_frontmatter
from harness.contracts.models import AgentFull, EntityFull, EntityMeta, SkillFull
from harness.contracts.protocol import EntityProvider
from harness.contracts.render import compact, render_l1_block

__all__ = [
    "AgentFull",
    "BaseFileProvider",
    "EntityFull",
    "EntityMeta",
    "EntityProvider",
    "SkillFull",
    "compact",
    "iter_entity_dirs",
    "render_l1_block",
    "split_frontmatter",
]
