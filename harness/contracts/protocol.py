"""EntityProvider 协议 —— agent / skill 共用的统一契约（读 + 写，全同步，CC 标准）。

对齐 Claude Code 后不含 route()：实体的「选择」由模型读 L1 description 完成。
读：reload（扫描）· list_l1（清单）· get（L2 全文，CC 字段映射进模型）。
写：write（模型 → CC frontmatter，自定义字段不写入——写入即收敛为 CC 标准）·
delete（删目录）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness.contracts.models import EntityFull


@runtime_checkable
class EntityProvider(Protocol):
    kind: str  # "agent" | "skill"

    def reload(self) -> int:
        """扫描 root → 重建 {name: EntityMeta} 索引；返回条目数。"""
        ...

    def list_l1(self, name_filter: set[str] | None = None) -> str:
        """渲染 L1 紧凑清单（模型自动调用目录，排除 disable-model-invocation）。

        name_filter 用于作用域收窄。
        """
        ...

    def get(self, name: str) -> EntityFull | None:
        """懒读 L2 全文；不存在返回 None。按名可显式加载（含 disable-model-invocation 项）。"""
        ...

    def has(self, name: str) -> bool: ...

    def names(self) -> list[str]:
        """模型可自动调用的实体名（排除 disable-model-invocation）。"""
        ...

    def all_names(self) -> list[str]:
        """全部实体名（含 disable-model-invocation），管理/CRUD 清单用。"""
        ...

    def write(self, name: str, full: EntityFull) -> None:
        """按 CC 标准写实体（模型 → frontmatter，自定义字段不写入）。"""
        ...

    def delete(self, name: str) -> bool:
        """删除实体目录；不存在返回 False。"""
        ...
