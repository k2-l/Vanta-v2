"""providers — 多 API 协议路由层（Anthropic / OpenAI）。

统一协议：模型引用可携带显式 `provider` 字段（手工选择）；缺省时按模型名前缀
智能推断（claude*→anthropic，gpt*/o*→openai），推断不出则回退 `default_provider`。

一处收敛所有 provider 差异，节点保持 provider 无关：
  - build_chat_model：按 provider 构造 ChatAnthropic / ChatOpenAI（凭据按 provider 取）
  - supports_prompt_cache / supports_thinking：provider 能力开关（cache_control、thinking 均 Anthropic 专属）
  - extract_usage：跨 provider 归一 token 用量（优先 LangChain usage_metadata）

刻意不 import 图内节点，保持叶子模块，杜绝循环导入。
"""

from __future__ import annotations

from typing import Any

from harness.contracts.models import ProviderName, normalize_provider_name
from harness.infra.settings import get_settings

ANTHROPIC = "anthropic"
OPENAI = "openai"
# 智能路由前缀表（小写匹配）。命中即判定 provider；都不命中回退 default_provider。
_OPENAI_PREFIXES = ("gpt-", "gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")
_ANTHROPIC_PREFIXES = ("claude-", "claude")


def infer_provider(model: str) -> ProviderName:
    """按模型名前缀智能推断 provider；推断不出回退 default_provider。"""
    m = (model or "").strip().lower()
    if m.startswith(_ANTHROPIC_PREFIXES):
        return ANTHROPIC
    if m.startswith(_OPENAI_PREFIXES):
        return OPENAI
    provider = normalize_provider_name(get_settings().default_provider, allow_none=False)
    assert provider is not None  # allow_none=False guarantees this
    return provider


def resolve_provider(explicit: str | None, model: str) -> ProviderName:
    """显式 provider 优先；仅缺省时智能推断，非法显式值立即报错。"""
    normalized = normalize_provider_name(explicit)
    if normalized is not None:
        return normalized
    return infer_provider(model)


def supports_prompt_cache(provider: str) -> bool:
    """cache_control（ephemeral 断点）为 Anthropic 结构专属；OpenAI 端点收到会报错。"""
    return provider == ANTHROPIC


def supports_thinking(provider: str) -> bool:
    """extended thinking（thinking 参数）为 Anthropic 专属。"""
    return provider == ANTHROPIC


def _provider_credentials(provider: str, s) -> tuple[str | None, str | None]:
    """按 provider 取 (api_key, base_url)；留空则由各 SDK 走默认（读环境变量）。"""
    if provider == OPENAI:
        return (s.openai_api_key or None), (s.openai_base_url or None)
    return (s.anthropic_api_key or None), (s.anthropic_base_url or None)


def build_chat_model(
    *,
    provider: str,
    model: str,
    max_tokens: int,
    thinking_budget: int | None = None,
) -> Any:
    """按 provider 构造裸 chat model（不含 bind_tools）。凭据按 provider 从 settings 取。"""
    resolved_provider = normalize_provider_name(provider, allow_none=False)
    assert resolved_provider is not None  # allow_none=False guarantees this
    provider = resolved_provider
    s = get_settings()
    api_key, base_url = _provider_credentials(provider, s)

    if provider == OPENAI:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        # thinking_budget 是 Anthropic 概念，OpenAI 侧忽略（reasoning 由模型自身控制）。
        return ChatOpenAI(**kwargs)

    # 默认 anthropic 分支（含第三方 Anthropic 兼容端点，如 DeepSeek /anthropic）
    from langchain_anthropic import ChatAnthropic

    kwargs = {"model": model, "max_tokens": max_tokens}
    # 凭据：Bearer/OAuth token（Claude Code OAuth、Bearer 代理）优先——走 Authorization 头、
    # 不发 x-api-key；否则用 x-api-key 风格的 api_key。二者至少其一由 _check_credentials 保证。
    if s.anthropic_auth_token:
        kwargs["default_headers"] = {"Authorization": f"Bearer {s.anthropic_auth_token}"}
    elif api_key:
        kwargs["anthropic_api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    if thinking_budget:
        # Anthropic 要求 max_tokens > thinking.budget_tokens，故在原 max_tokens 之外再留出该预算
        kwargs["max_tokens"] = max_tokens + thinking_budget
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    return ChatAnthropic(**kwargs)


def extract_usage(response: Any) -> tuple[int | None, int | None, int, int]:
    """跨 provider 归一 token 用量：返回 (input, output, cache_read, cache_created)。

    优先 LangChain 归一化的 usage_metadata（Anthropic/OpenAI 均填充）；
    缺失时回退原始 response_metadata['usage']（Anthropic 字段名）。
    input/output 缺失返回 None，交由调用方用本地估算兜底。
    """
    um = getattr(response, "usage_metadata", None)
    if um:
        details = um.get("input_token_details", {}) or {}
        return (
            um.get("input_tokens"),
            um.get("output_tokens"),
            int(details.get("cache_read", 0) or 0),
            int(details.get("cache_creation", 0) or 0),
        )
    usage = getattr(response, "response_metadata", {}).get("usage", {}) or {}
    return (
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        int(usage.get("cache_read_input_tokens", 0) or 0),
        int(usage.get("cache_creation_input_tokens", 0) or 0),
    )
