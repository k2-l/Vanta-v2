"""轻量重试装饰器：针对 Anthropic / 第三方兼容服务的瞬时错误。

不引入 tenacity 依赖。规则：
  - 指数退避 1s / 2s / 4s（最多 3 次重试）
  - 仅重试可重试错误：connection error / timeout / 429 / 5xx
  - 4xx (除 429) 立即上抛
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import Any, TypeVar

from harness.infra.logging import log

T = TypeVar("T")

MAX_RETRIES = 3
BACKOFF_BASE = 1.0


def _is_retryable(exc: BaseException) -> bool:
    # anthropic SDK 异常类
    name = type(exc).__name__
    if name in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "APIError",
    }:
        return True
    # httpx / asyncio
    if name in {"ConnectError", "ReadTimeout", "ReadError", "RemoteProtocolError"}:
        return True
    # status code 嗅探
    status = getattr(exc, "status_code", None)
    if status is not None:
        if status == 429 or 500 <= status < 600:
            return True
    return False


def with_retry(
    fn: Callable[..., Any] | None = None,
    *,
    max_retries: int = MAX_RETRIES,
    base: float = BACKOFF_BASE,
):
    """异步函数装饰器：失败时指数退避重试。"""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001
                    if not _is_retryable(exc) or attempt >= max_retries:
                        raise
                    delay = base * (2**attempt)
                    log.warning(
                        "retry.backoff",
                        attempt=attempt + 1,
                        delay_s=delay,
                        exc_type=type(exc).__name__,
                        exc=str(exc)[:200],
                    )
                    await asyncio.sleep(delay)
                    last_exc = exc
            raise RuntimeError(
                "retry loop exited without exception — this is a bug"
            ) from last_exc

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator
