"""capabilities/utils — 域能力之间的共同逻辑与数据结构。

- EntityContent  : Agent / Skill 等「实体完整内容」的共同字段基类（各域继承补充专属字段）。
- render_l1_block: L1 紧凑清单渲染（AgentRegistry / SkillRegistry 共用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EntityContent:
    """实体（Agent / Skill）完整内容的共同字段。子类追加各自专属字段。"""

    name: str
    description: str
    content: str
    model: str | None


def render_l1_block(
    index: dict[str, Any],
    header: str,
    name_filter: set[str] | None = None,
    *,
    with_keywords: bool = False,
) -> str:

    entries = index if name_filter is None else {k: v for k, v in index.items() if k in name_filter}
    if not entries:
        return ""
    
    lines = [header]
    for name, entry in entries.items():
        # 兼容两种数据格式
        if isinstance(entry, dict):
            # 完整格式: {"compact": str, "keywords": [...]}
            compact = entry.get("compact", "")
            suffix = ""
            if with_keywords:
                kw = entry.get("keywords", [])
                suffix = f" [关键词: {', '.join(kw[:5])}]" if kw else ""
            lines.append(f"- **{name}**: {compact}{suffix}")
        else:
            # 简化格式 (BaseRegistry 标准): 直接是字符串
            lines.append(f"- **{name}**: {entry}")
    
    return "\n".join(lines)