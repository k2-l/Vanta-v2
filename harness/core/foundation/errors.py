"""Agent 错误分类常量。

集中定义错误模式、恢复提示、退避时长和不可重试错误集合，
供 harness.core.graph.nodes 和 subgraph.py 共用，避免重复定义。
"""

from __future__ import annotations

import re

_ERROR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"timed?\s*out|timeout"), "TIMEOUT"),
    (re.compile(r"command not found|no such file"), "COMMAND_NOT_FOUND"),
    (re.compile(r"connection (refused|reset|failed|error)"), "CONNECTION_FAILED"),
    (re.compile(r"permission denied|access denied"), "PERMISSION_DENIED"),
    (re.compile(r"rate.?limit|429"), "RATE_LIMIT"),
    (re.compile(r"\b401\b|authentication fail|invalid.*api.?key|unauthorized", re.I), "AUTH_ERROR"),
    (re.compile(r"\b403\b|forbidden", re.I), "AUTH_ERROR"),
    (re.compile(r"invalid_api_key|incorrect.*key|api key.*invalid", re.I), "AUTH_ERROR"),
]

_RECOVERY_PROMPTS: dict[str, str] = {
    "TIMEOUT": "上一步超时。请缩小操作范围或拆分成更小的步骤。",
    "CONNECTION_FAILED": "网络连接失败。请确认目标地址可达，或稍后重试。",
    "RATE_LIMIT": "API 请求频率超限，已短暂等待。请适当降低并发数。",
    "TOOL_LOOP": "检测到工具调用循环，已超过最大迭代次数。请总结当前进展并给出最终结论，不再调用工具。",
    "UNKNOWN": "发生未知错误。请分析错误信息，尝试不同的方法。",
}

# 每种错误类型在不同重试次数时的等待秒数（递增）
_BACKOFF_SECONDS: dict[str, list[float]] = {
    "RATE_LIMIT": [2.0, 8.0, 30.0],
    "CONNECTION_FAILED": [1.0, 3.0, 8.0],
    "TIMEOUT": [0.0, 0.5, 1.0],
    "UNKNOWN": [0.5, 1.5, 4.0],
}

# 结构性错误：重试无意义，直接终止，不消耗重试次数
_NON_RETRYABLE_ERRORS: frozenset[str] = frozenset(
    {
        "COMMAND_NOT_FOUND",  # 命令/文件不存在，重试结果相同
        "PERMISSION_DENIED",  # 权限不足，重试不会改变权限
        "AUTH_ERROR",  # 401/403：key 无效，重试不会改变认证状态
    }
)


def classify_error(error: str) -> str:
    low = error.lower()
    for pattern, label in _ERROR_PATTERNS:
        if pattern.search(low):
            return label
    return "UNKNOWN"


_ERROR_SEVERITY: dict[str, int] = {
    "AUTH_ERROR": 6,
    "PERMISSION_DENIED": 5,
    "BUDGET_EXCEEDED": 4,
    "CONTEXT_LIMIT": 3,
    "TIMEOUT": 2,
}


def most_severe_error_type(errors: list[str]) -> str:
    """分类一批错误串并返回严重度最高的 error_type（调用方需保证 errors 非空）。"""
    return max((classify_error(e) for e in errors), key=lambda t: _ERROR_SEVERITY.get(t, 1))
