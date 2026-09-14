from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from harness.core.graph.providers import build_chat_model, resolve_provider
from harness.infra.logging import log

# 用户主动压缩：结构化交接摘要的系统指令（结构化 + 「新覆盖旧」淘汰过期信息）
_COMPACTION_SYSTEM = (
    "你是对话上下文压缩器。把下面的对话历史压缩成一份**结构化交接摘要**，"
    "供后续对话作为背景继续使用。严格按以下分块输出（某块无内容就写「无」）：\n"
    "## 目标与需求\n## 关键发现与事实\n## 已完成\n## 当前进展与待办\n\n"
    "规则：\n"
    "- 后出现的信息若与先前冲突，**只保留最新状态**；已放弃或已解决的线程不要再列。\n"
    "- 保留具体的名称、路径、IP、命令、数字、结论等硬事实；去掉寒暄与冗余叙述。\n"
    "- 只输出摘要本身，不要加任何前后缀说明。"
)


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
    context: str, target_chars: int, model_name: str, provider: str | None = None
) -> str:
    prompt = (
        f"请将以下内容总结为不超过 {target_chars} 个字符的精炼摘要，"
        "保留所有关键结论、数据和决策依据，去除冗余叙述。"
        "直接输出摘要，不加任何前缀说明。\n\n"
        f"{context}"
    )
    try:
        model = build_chat_model(
            provider=resolve_provider(provider, model_name),
            model=model_name,
            max_tokens=max(512, target_chars // 3),
        )
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        summary = _extract_text(resp.content).strip()
        log.info(
            "context.compressed", original=len(context), summary=len(summary), model=model_name
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        log.warning("context.compress_failed", exc=str(exc)[:200])
        return context[:target_chars] + f"\n…[摘要失败，已截断至 {target_chars} 字符]"


async def compact_session_history(
    transcript: str,
    *,
    prev_summary: str = "",
    model_name: str,
    provider: str | None = None,
    max_tokens: int = 1024,
) -> str:
    """把一段对话历史原文（transcript）压成结构化交接摘要。

    prev_summary 为上一份摘要（覆盖更早、可能已过期的历史）；新历史与其冲突时以新历史为准。
    失败时**抛出异常**（不静默返回残缺结果）——用户主动触发，交由上层返回错误并允许重试。
    """
    parts: list[str] = []
    if prev_summary.strip():
        parts.append(
            "【已有摘要（更早历史；如与下方新对话冲突，以新对话为准覆盖）】\n"
            + prev_summary.strip()
        )
    parts.append("【对话历史】\n" + transcript)
    user = "\n\n".join(parts)

    model = build_chat_model(
        provider=resolve_provider(provider, model_name),
        model=model_name,
        max_tokens=max_tokens,
    )
    resp = await model.ainvoke(
        [SystemMessage(content=_COMPACTION_SYSTEM), HumanMessage(content=user)]
    )
    summary = _extract_text(resp.content).strip()
    log.info(
        "context.compacted",
        transcript=len(transcript),
        summary=len(summary),
        model=model_name,
    )
    return summary
