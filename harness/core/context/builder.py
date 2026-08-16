"""L1 清单注入块生成 —— 委托给 EntityProvider（agent + skill）。

数据源: 文件系统（provider 内部扫描 workspace/{agents,skills}/<name>/*.md）。
注入 token 上限 MAX_INJECT_TOKENS（默认 3000）：超限降级为 name-only。
结果缓存 _CACHE_TTL 秒；invalidate_context_cache() 强制失效并重扫 provider 索引。
"""

from __future__ import annotations

import time

from harness.core.foundation.tokens import count_tokens
from harness.infra.logging import log
from harness.providers import get_provider, reload_all

MAX_INJECT_TOKENS = 3_000
_CACHE_TTL = 30.0

_l1_cache: tuple[str, float] | None = None


def invalidate_context_cache() -> None:
    """清除 L1 缓存并重扫 provider 索引（CRUD 写入后调用）。"""
    global _l1_cache
    _l1_cache = None
    try:
        reload_all()
    except Exception:
        pass


async def load_and_build() -> str:
    """合并 Agent + Skill 的 L1 清单；token 超限降级为 name-only。结果缓存 _CACHE_TTL 秒。"""
    global _l1_cache
    now = time.monotonic()
    if _l1_cache is not None and (now - _l1_cache[1]) < _CACHE_TTL:
        return _l1_cache[0]

    try:
        agent_p = get_provider("agent")
        skill_p = get_provider("skill")
        full_block = "\n\n".join(b for b in (agent_p.list_l1(), skill_p.list_l1()) if b)

        if count_tokens(full_block) <= MAX_INJECT_TOKENS:
            result = full_block
        else:
            log.warning(
                "context_builder.token_budget_exceeded",
                limit=MAX_INJECT_TOKENS,
                fallback="name_only",
            )
            agent_names = ", ".join(agent_p.names())
            skill_names = ", ".join(skill_p.names())
            result = "\n\n".join(
                b
                for b in (
                    f"# 可用 Agent\n{agent_names}" if agent_names else "",
                    f"# 可用 Skill\n{skill_names}" if skill_names else "",
                )
                if b
            )
            if count_tokens(result) > MAX_INJECT_TOKENS:
                result = result[: MAX_INJECT_TOKENS * 3]
    except Exception as exc:  # noqa: BLE001
        log.warning("context_builder.load_failed", exc=str(exc)[:100])
        result = ""

    _l1_cache = (result, now)
    return result


async def load_dep_context() -> str:
    """依赖上下文：文件系统模式下无此概念，返回空字符串。"""
    return ""
