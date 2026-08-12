"""models — ChatAnthropic 模型工厂与缓存（叶子模块，无图内依赖）。

集中两类模型缓存，供主图节点（nodes/agent.py · summarize.py）与子图（subagent/）共用：
  - _get_base_model：裸 ChatAnthropic（lru_cache，按 model 参数组合缓存）
  - _bound_model_cache：bind_tools 后的模型（按 model 参数 + 工具快照缓存）

刻意不 import nodes / subagent，保持为叶子模块，杜绝包初始化循环。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_anthropic import ChatAnthropic

# _bound_model_cache caches ChatAnthropic-with-tools (bound) objects keyed by
# (model, api_key, base_url, max_tokens, tools_hash). Separate from _get_base_model
# because bound models depend on the tool registry snapshot, not just model params.
_bound_model_cache: dict[tuple, Any] = {}


@lru_cache(maxsize=8)
def _get_base_model(
    model: str,
    api_key: str | None,
    base_url: str | None,
    max_tokens: int,
    thinking_budget: int | None = None,
) -> ChatAnthropic:
    """缓存裸 ChatAnthropic 对象（不含 bind_tools）。

    与 _bound_model_cache 互补：此缓存针对 model 参数组合（无工具绑定），
    供 summarize_node 和 subagent 使用。key = (model, api_key, base_url, max_tokens, thinking_budget)。
    """
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if api_key:
        kwargs["anthropic_api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    if thinking_budget:
        # Anthropic 要求 max_tokens > thinking.budget_tokens，故在原 max_tokens 之外再留出该预算
        kwargs["max_tokens"] = max_tokens + thinking_budget
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    return ChatAnthropic(**kwargs)


def clear_model_caches() -> None:
    """清空 base-model（lru_cache）与 bound-model 缓存。

    infra.config_store 在每次配置写入后调用，使下次 agent 调用立即采用新的
    model / api_key / max_tokens；取代外部直接 reach 进 _get_base_model / _bound_model_cache。
    """
    _get_base_model.cache_clear()
    _bound_model_cache.clear()
