"""Token 计数与截断（纯叶子工具，仅依赖 tiktoken）。

从 token_budget.py / runtime.py 抽出，消除两套重复实现。
不依赖 infra/db —— 任何模块都可安全导入而不被迫拉进 DB 层。
Token 计数：tiktoken cl100k_base（Claude 模型的合理近似）。
"""

from __future__ import annotations

from typing import Any

import tiktoken

_enc: tiktoken.Encoding | None = None


def _get_enc() -> tiktoken.Encoding:
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding("cl100k_base")
    return _enc


def count_tokens(text: str) -> int:
    """估算字符串的 token 数（tiktoken cl100k_base）。"""
    if not text:
        return 0
    try:
        return len(_get_enc().encode(text, disallowed_special=()))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 4)


def count_messages_tokens(messages: list[Any]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for m in messages:
        if hasattr(m, "content"):
            c = m.content
            if isinstance(c, str):
                total += count_tokens(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict):
                        total += count_tokens(block.get("text", "") or str(block))
    return total


def estimate_tokens(text: str) -> int:
    """廉价、CJK 感知的 token 估算；精确边界仍用 count_tokens。"""
    if not text:
        return 0
    cjk = sum(
        1
        for char in text
        if "\u3400" <= char <= "\u9fff"
        or "\u3040" <= char <= "\u30ff"
        or "\uac00" <= char <= "\ud7af"
    )
    non_cjk = len(text) - cjk
    return max(1, (cjk * 2 + 2) // 3 + non_cjk // 4)


def estimate_messages_tokens(messages: list[Any]) -> int:
    """消息列表的廉价 token 估算（不跑 tiktoken）。"""
    total = 0
    for m in messages:
        c = getattr(m, "content", None)
        if isinstance(c, str):
            total += estimate_tokens(c)
        elif isinstance(c, list):
            total += sum(
                estimate_tokens(b.get("text", "") or str(b))
                for b in c
                if isinstance(b, dict)
            )
    return total


def truncate_to_tail_tokens(text: str, max_tokens: int) -> str:
    """保留文本末尾 max_tokens 个 token（按 token 边界对齐）。"""
    enc = _get_enc()
    ids = enc.encode(text, disallowed_special=())
    if len(ids) <= max_tokens:
        return text
    return enc.decode(ids[-max_tokens:])
