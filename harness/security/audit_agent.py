"""审计 Agent 审批门 —— HITL 的 LLM 自动审批方。

Vanta 已有权限引擎（permissions.py：allow/ask/deny）+ 人工审批（approvals.py：
request_approval 阻塞等前端决策）。本模块补上第三种审批方：当某工具调用被判为 "ask"
且 settings.approval_reviewer == "audit_agent" 时，用 model_low 快速裁决，代替阻塞人工。

裁决基调「默认放行、只拦破坏性动作」的审计 prompt 借鉴自 CyberStrikeAI（Apache-2.0，
github.com/Ed1s0nZ/CyberStrikeAI），按 Vanta / 嘤嘤 语境改写。

与人工审批同为 **fail-closed**：LLM 调用异常 / 解析失败 → 视为拒绝，绝不放行未知。
"""

from __future__ import annotations

import json
import re
from typing import Any

from harness.infra.anthropic import build_anthropic_client
from harness.infra.logging import log
from harness.infra.settings import get_settings

_AUDIT_TIMEOUT = 30.0
_AUDIT_MAX_TOKENS = 256

_AUDIT_SYSTEM = """你是嘤嘤（AI 渗透测试助手）的人机协同审计员。审查 agent 即将执行的工具调用是否会对系统造成实质性损害。

你会收到一个 JSON，含 toolName、arguments、message 等字段。

裁决基调（默认放行）：
- 常规、低风险的渗透测试 / 只读操作 → approve（信息收集、端口/服务扫描、目录枚举、只读查询、无害探测命令）
- 与当前任务目标一致、未见明确高危迹象 → approve

必须 reject 的高危情形（示例，非穷举）：
- 删库、清表、批量删除数据、rm -rf、格式化磁盘、不可逆破坏
- 修改/重置密码、创建或篡改管理员账号、植入持久化后门、开机自启
- 向生产环境写入恶意载荷、勒索加密、停止关键服务、篡改系统核心配置
- 明显越权：与任务目标无关的破坏性操作

不应单独作为 reject 理由：
- 常规 nmap/curl/grep/读文件/枚举类命令本身
- 参数略宽泛但无明确破坏意图
- 仅因「信息不足」——若无上述高危迹象，应 approve，可在 comment 里提示注意点

仅输出一行 JSON，不要 markdown 代码块，不要额外文字：
{"decision":"approve"|"reject","comment":"简要理由（中文，不超过 60 字）"}"""


def _extract_decision(text: str) -> dict[str, Any] | None:
    """从 LLM 输出里抠出 {"decision","comment"} JSON。容忍代码块包裹与前后噪音。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = m.group(1).strip() if m else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


async def audit_review(
    session_id: str,
    tool_name: str,
    tool_input: dict,
    message: str,
) -> tuple[bool, str]:
    """审计 Agent 裁决一次工具调用，返回 (approved, comment)。

    fail-closed：任何异常 / 无法解析 / decision 非 approve → (False, 原因)。
    """
    s = get_settings()
    payload = json.dumps(
        {"toolName": tool_name, "arguments": tool_input, "message": message},
        ensure_ascii=False,
        default=str,
    )[:4000]

    try:
        client = build_anthropic_client(timeout=_AUDIT_TIMEOUT)
        resp = await client.messages.create(
            model=s.model_low,
            max_tokens=_AUDIT_MAX_TOKENS,
            system=_AUDIT_SYSTEM,
            messages=[{"role": "user", "content": payload}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        data = _extract_decision(text)
        if data is None:
            log.warning("audit_agent.parse_failed", tool_name=tool_name, preview=text[:200])
            return False, "审计 Agent 输出无法解析，fail-closed 拒绝"
        approved = str(data.get("decision", "")).strip().lower() == "approve"
        comment = str(data.get("comment", "")).strip()[:200]
        log.info(
            "audit_agent.decision",
            tool_name=tool_name,
            session_id=session_id,
            approved=approved,
            comment=comment[:120],
        )
        return approved, comment or ("放行" if approved else "拒绝")
    except Exception as exc:  # noqa: BLE001 — fail-closed
        log.warning("audit_agent.error", tool_name=tool_name, error=str(exc)[:200])
        return False, f"审计 Agent 调用失败（{type(exc).__name__}），fail-closed 拒绝"
