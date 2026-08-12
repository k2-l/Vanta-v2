"""services — 绕运行时的辅助服务。

- maybe_generate_title : 会话标题自动生成（LLM，model_low→model_mid 兜底）。
"""

from __future__ import annotations

from sqlalchemy import select as _sa_select

from harness.infra import db
from harness.infra.anthropic import build_anthropic_client
from harness.infra.db import Session as _Session
from harness.infra.db import session_factory as _session_factory
from harness.infra.logging import log
from harness.infra.retry import with_retry
from harness.infra.settings import get_settings

# ═══ 会话标题生成：titler ═════════════════════════════════════════════════

_DEFAULT_TITLE = "新会话"
_TITLE_PROMPT = (
    "请为以下对话生成一个 6-15 个字的中文标题，"
    "概括用户的核心意图。只输出标题文字本身，不要引号、不要标点结尾、不要解释。\n\n"
    "用户：{user}\n助手：{assistant}\n\n标题："
)


@with_retry
async def _ask_title(user_msg: str, assistant_msg: str, model: str) -> str:
    client = build_anthropic_client(timeout=30.0)
    resp = await client.messages.create(
        model=model,
        # 512 而非 60：deepseek-v4-flash 等推理模型先产出 thinking block，max_tokens
        # 太小会被思考过程吃光（stop_reason=max_tokens，零 text block），导致标题恒为空、
        # 自动命名静默失效。标题最终只取前 30 字，留足思考预算后再产出短标题即可。
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": _TITLE_PROMPT.format(user=user_msg[:500], assistant=assistant_msg[:1000]),
            }
        ],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text.strip("\"'。．. \n\t")[:30]


async def maybe_generate_title(session_id: str) -> str | None:
    """检查并生成标题。返回新标题，或 None 表示未触发。"""
    async with _session_factory()() as _db:
        result = await _db.execute(_sa_select(_Session.title).where(_Session.id == session_id))
        current_title = result.scalar()
    if current_title is None:
        return None
    if current_title and current_title != _DEFAULT_TITLE:
        return None
    msgs = await db.recent_messages(session_id, n=4)
    user_msgs = [m for m in msgs if m.role == "user"]
    asst_msgs = [m for m in msgs if m.role == "assistant"]
    if not user_msgs or not asst_msgs:
        return None

    s = get_settings()
    # model_low 优先；调用失败或返回空时回退到 model_mid（主聊天同款，已知可用）——
    # 兼容第三方端点（如 deepseek）未单独配置 [models].low、低级模型名不被识别的情况。
    candidates = [s.model_low]
    if s.model_mid and s.model_mid != s.model_low:
        candidates.append(s.model_mid)

    title = ""
    for i, model in enumerate(candidates):
        last = i == len(candidates) - 1
        try:
            title = await _ask_title(user_msgs[0].content, asst_msgs[0].content, model)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "titler.failed" if last else "titler.fallback",
                session_id=session_id,
                model=model,
                exc=str(exc)[:200],
            )
            continue
        if title:
            break
        if not last:
            log.warning("titler.fallback", session_id=session_id, model=model, reason="empty_result")

    if not title:
        # 所有候选模型都返回空标题（典型：推理模型把 max_tokens 预算耗在 thinking
        # block 上、零 text 输出）——记一行日志，避免自动命名静默失效后难以排查。
        log.info("titler.empty", session_id=session_id, candidates=candidates)
        return None
    await db.update_title(session_id, title)
    log.info("titler.ok", session_id=session_id, title=title)
    return title
