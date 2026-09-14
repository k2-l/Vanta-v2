"""过滤只供 Agent 内部使用的标记，保证流式输出和持久化使用同一边界。"""

from __future__ import annotations

import re

_TAGS = ("scratchpad", "subgoal")
_COMPLETE = {
    tag: re.compile(rf"<{tag}\b[^>]*>[\s\S]*?</{tag}\s*>\s*", re.IGNORECASE)
    for tag in _TAGS
}
_UNCLOSED = {
    tag: re.compile(rf"<{tag}\b[^>]*>[\s\S]*$", re.IGNORECASE) for tag in _TAGS
}
_OPENINGS = tuple(f"<{tag}>" for tag in _TAGS)


def strip_internal_sections(text: str) -> str:
    """移除完整/未闭合内部区段，并保留普通公开文本。"""
    public = text
    for tag in _TAGS:
        public = _COMPLETE[tag].sub("", public)
        public = _UNCLOSED[tag].sub("", public)

    # 流式 chunk 可能停在 '<scr'；先暂存可能的起始标签前缀，避免标签闪现。
    max_prefix = 0
    lowered = public.lower()
    for opening in _OPENINGS:
        for size in range(1, len(opening)):
            if lowered.endswith(opening[:size]):
                max_prefix = max(max_prefix, size)
    if max_prefix:
        public = public[:-max_prefix]
    return public


class InternalSectionStreamFilter:
    """按任意 chunk 边界增量输出公开文本。"""

    def __init__(self) -> None:
        self._raw = ""
        self._public = ""

    def feed(self, chunk: str) -> str:
        self._raw += chunk
        public = strip_internal_sections(self._raw)
        if not public.startswith(self._public):
            # 防御异常/畸形标签：绝不撤回已发文本，也不重复发射。
            return ""
        delta = public[len(self._public) :]
        self._public = public
        return delta

    @property
    def public_text(self) -> str:
        return self._public
