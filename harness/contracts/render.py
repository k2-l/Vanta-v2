"""L1 紧凑清单渲染（Agent / Skill 共用，零依赖）。"""

from __future__ import annotations


def compact(text: str, limit: int = 100) -> str:
    """取 description 的首行并截断，作为 L1 紧凑描述。"""
    if not text or not text.strip():
        return "无描述"
    first = text.strip().splitlines()[0].strip()
    return f"{first[:limit]}…" if len(first) > limit else first


def render_l1_block(entries: dict[str, str], header: str) -> str:
    """把 {name: 紧凑描述} 渲染为可注入 System Prompt 的 Markdown 清单。"""
    if not entries:
        return ""
    lines = [header]
    for name, desc in entries.items():
        lines.append(f"- **{name}**: {desc}")
    return "\n".join(lines)
