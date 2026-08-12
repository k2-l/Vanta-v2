"""喂 LLM / 落盘前，给工具输出里的高置信凭据打码为 [REDACTED:LABEL]。

防敏感数据外泄到第三方 LLM；与 sanitizer(防 prompt 注入)职责互补。
保守取向：只打码有明确前缀/结构或 key=value 形态的凭据，宁漏勿错杀。
"""

from __future__ import annotations

import re

# (pattern, label, group_to_mask)：group 0 = 整段命中；>0 = 只打码该捕获组（保留 key 名/host）
_RULES: list[tuple[re.Pattern[str], str, int]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "PRIVATE_KEY",
        0,
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS_KEY", 0),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "GITHUB_TOKEN", 0),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), "GITHUB_PAT", 0),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "SLACK_TOKEN", 0),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "JWT",
        0,
    ),
    # user:pass@host（URL 内联密码）—— 只打码密码段
    (re.compile(r"://[^/\s:@]+:([^@/\s]{3,})@"), "URL_PASSWORD", 1),
    # Authorization / Bearer 头 —— 只打码凭据值
    (re.compile(r"(?i)\b(authorization|bearer)\b\s*[:=]?\s*([A-Za-z0-9._\-]{16,})"), "AUTH", 2),
    # 通用 key=value 凭据 —— 只打码值，保留 key 名
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key|private[_-]?key)\b"
            r"\s*[:=]\s*[\"']?([^\s\"',;]{8,})"
        ),
        "CREDENTIAL",
        2,
    ),
]


def _mask(m: re.Match[str], label: str, group: int) -> str:
    """把命中处替换为 [REDACTED:label]；group>0 时只替换该捕获组。"""
    if group == 0:
        return f"[REDACTED:{label}]"
    whole, secret = m.group(0), m.group(group)
    if not secret:
        return whole
    idx = whole.rfind(secret)  # 从右起，避免误打码与 secret 同形的 key 名
    return whole[:idx] + f"[REDACTED:{label}]" + whole[idx + len(secret) :]


def redact(text: str) -> tuple[str, int]:
    """给文本里的高置信凭据打码。返回 (脱敏文本, 命中计数)。"""
    if not text:
        return text, 0
    total = 0
    for pattern, label, group in _RULES:
        text, n = pattern.subn(lambda m, la=label, gr=group: _mask(m, la, gr), text)
        total += n
    return text, total
