from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from harness.infra.logging import log


def _extract_text(content: Any) -> str:
    if not content and content != 0:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


async def _compress_context(
    context: str, target_chars: int, model_name: str, api_key: str | None, base_url: str | None
) -> str:
    prompt = (
        f"请将以下内容总结为不超过 {target_chars} 个字符的精炼摘要，"
        "保留所有关键结论、数据和决策依据，去除冗余叙述。"
        "直接输出摘要，不加任何前缀说明。\n\n"
        f"{context}"
    )
    kwargs: dict[str, Any] = {"model": model_name, "max_tokens": max(512, target_chars // 3)}
    if api_key:
        kwargs["anthropic_api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    try:
        model = ChatAnthropic(**kwargs)
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        summary = _extract_text(resp.content).strip()
        log.info(
            "context.compressed", original=len(context), summary=len(summary), model=model_name
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        log.warning("context.compress_failed", exc=str(exc)[:200])
        return context[:target_chars] + f"\n…[摘要失败，已截断至 {target_chars} 字符]"
