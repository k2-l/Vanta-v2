"""Token 用量与成本估算。

第三方兼容服务可能不返回准确的 usage，或定价不同。
我们记录 raw token 数 + 给出 Anthropic 官方价的成本估算（仅参考）。
定价表由 Settings.price_per_m_tokens 管理，可通过 config.json 覆盖。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from harness.core.foundation.registry import LRUDict

_MAX_TRACKED_SESSIONS = 10_000  # 超出时驱逐最久未访问的 session，防止内存无限增长


def _get_price_table() -> dict[str, tuple[float, float]]:
    """返回当前定价表（从 Settings 读取，支持运行时覆盖）。"""
    from harness.infra.settings import get_settings

    raw = get_settings().price_per_m_tokens
    # Settings 存储为 list[float] 以兼容 JSON/TOML；此处转为 tuple[float, float]
    return {k: (v[0], v[1]) for k, v in raw.items() if len(v) >= 2}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    def cost_usd(self) -> float:
        prices = _get_price_table().get(self.model)
        if prices is None:
            return 0.0
        in_p, out_p = prices
        return (self.input_tokens * in_p + self.output_tokens * out_p) / 1_000_000

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            model=self.model if self.model == other.model else "mixed",
        )


@dataclass
class SessionUsage:
    session_id: str
    total: Usage = field(default_factory=Usage)
    by_model: dict[str, Usage] = field(default_factory=lambda: defaultdict(Usage))


class UsageTracker:
    """进程内 in-memory 计数。asyncio 单线程，无需锁。

    _sessions 使用 LRUDict 实现上限，防止长时间运行进程内存无限增长。
    """

    def __init__(self) -> None:
        self._sessions: LRUDict = LRUDict(maxsize=_MAX_TRACKED_SESSIONS)

    def add(self, session_id: str, model: str, input_tokens: int, output_tokens: int) -> None:
        """原地更新计数，零对象分配（除非 session/model 首次出现）。"""
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)  # 标记为最近访问
        else:
            self._sessions[session_id] = SessionUsage(session_id=session_id)  # LRUDict 自动驱逐 LRU

        su = self._sessions[session_id]

        # total 原地更新
        su.total.input_tokens += input_tokens
        su.total.output_tokens += output_tokens
        if su.total.model not in ("", model):
            su.total.model = "mixed"
        elif not su.total.model:
            su.total.model = model

        # per-model 原地更新；首次见到该 model 才分配新对象
        if model not in su.by_model:
            su.by_model[model] = Usage(model=model)
        mu = su.by_model[model]
        mu.input_tokens += input_tokens
        mu.output_tokens += output_tokens

    def get(self, session_id: str) -> SessionUsage:
        su = self._sessions.get(session_id)
        if su is not None:
            self._sessions.move_to_end(session_id)  # 访问即更新 LRU 顺序
        return su if su is not None else SessionUsage(session_id=session_id)


_tracker = UsageTracker()


def tracker() -> UsageTracker:
    return _tracker
