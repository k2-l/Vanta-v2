"""共享 Anthropic 客户端构造。

抽到 infra 是为了避免 agent.runtime ↔ agent.workers.tool_worker 之间的循环导入。
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from harness.infra.settings import get_settings


def build_anthropic_client(timeout: float | None = None) -> AsyncAnthropic:
    s = get_settings()
    kwargs: dict[str, Any] = {}
    if s.anthropic_api_key:
        kwargs["api_key"] = s.anthropic_api_key
    if s.anthropic_auth_token:
        kwargs["auth_token"] = s.anthropic_auth_token
    if s.anthropic_base_url:
        kwargs["base_url"] = s.anthropic_base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AsyncAnthropic(**kwargs)
