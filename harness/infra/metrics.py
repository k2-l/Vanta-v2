"""轻量级进程内指标计数器。

设计：纯 Python defaultdict，零外部依赖，零锁。
所有调用方均在 asyncio 事件循环单线程内，CPython GIL 保证
  `defaultdict.__setitem__` 和整数自增在字节码层面是原子的。
GET /metrics 返回当前快照（进程级，重启清零）。

计数键约定：
  llm.calls          — LLM 推理调用次数（成功）
  llm.errors         — LLM 推理调用失败次数
  llm.cache.prompt   — prompt cache 命中次数（Anthropic cache_read_input_tokens > 0）
  tool.exec.ok       — 工具执行成功次数
  tool.exec.fail     — 工具执行失败次数
  tool.cache.hit     — 工具结果缓存命中次数
  tool.model_cache   — bind_tools 缓存命中次数
  injection.detected — 检测到 prompt injection 次数
  route.*            — 路由分支计数（route.agent.tools / recovery / summarize 等）
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime

_counters: dict[str, int] = defaultdict(int)
_start_time: float = time.time()
_start_iso: str = datetime.now(UTC).isoformat()


def inc(key: str, amount: int = 1) -> None:
    """递增计数器。asyncio 单线程，无需锁。"""
    _counters[key] += amount


def snapshot() -> dict[str, object]:
    """返回所有计数器的当前快照 + 进程启动时间。"""
    return {
        "uptime_sec": round(time.time() - _start_time, 1),
        "started_at": _start_iso,
        "counters": dict(_counters),
    }


def reset() -> None:  # pragma: no cover — 仅限测试环境调用
    """⚠ 测试专用：重置所有计数器。生产代码不应调用此函数。"""
    _counters.clear()
