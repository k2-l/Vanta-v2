"""models — 跨 provider 模型工厂与缓存（叶子模块，无图内依赖）。

集中两类模型缓存，供主图节点（nodes/agent.py · summarize.py）与子图（subagent/）共用：
  - _get_base_model：裸 chat model（lru_cache，按 provider+model 参数组合缓存）
  - _bound_model_cache：bind_tools 后的模型（按 provider+model 参数 + 工具快照缓存）

provider 差异（Anthropic / OpenAI 的构造、cache、thinking、usage）收敛在
harness.core.graph.providers；本模块只做缓存。刻意不 import nodes / subagent，
保持为叶子模块，杜绝包初始化循环。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from harness.core.graph.providers import build_chat_model

# _bound_model_cache caches chat-model-with-tools (bound) objects keyed by
# (provider, model, max_tokens, thinking_budget, tools_hash, disclosed). Separate from
# _get_base_model because bound models depend on the tool registry snapshot, not just model params.
_bound_model_cache: dict[tuple, Any] = {}


@lru_cache(maxsize=16)
def _get_base_model(
    model: str,
    max_tokens: int,
    thinking_budget: int | None = None,
    provider: str = "anthropic",
) -> Any:
    """缓存裸 chat model 对象（不含 bind_tools）。

    provider 决定构造 ChatAnthropic 还是 ChatOpenAI；凭据由 providers 层按 provider 取。
    key = (model, max_tokens, thinking_budget, provider)；凭据变更经 clear_model_caches 生效。
    """
    return build_chat_model(
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        thinking_budget=thinking_budget,
    )


def clear_model_caches() -> None:
    """清空 base-model（lru_cache）与 bound-model 缓存。

    infra.config_store 在每次配置写入后调用，使下次 agent 调用立即采用新的
    model / api_key / max_tokens / provider；取代外部直接 reach 进缓存。
    """
    _get_base_model.cache_clear()
    _bound_model_cache.clear()
