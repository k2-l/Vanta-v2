"""Tool output sanitizer — prompt injection 防御层。

策略：把 tool output 用 XML 沙箱包裹、标记可疑注入模式，并**中和沙箱定界符逃逸**
（ingested 内容混入 `</tool_output>` 冲破边界）。不截断内容（保留可审计性），
只告知 LLM 该区块是不可信纯数据 + 命中了哪些注入标志。

可信工具（TRUSTED_TOOLS）输出来自内部 DB，跳过检测直接返回，省标签 token。

侦察摄入的靶标可控内容（网页 / banner / HTTP 头 / 证书）是头等注入面，故规则覆盖
中英双语 + LLM 控制 token + 提示词泄露 / 数据外泄诱导 + 零宽 / 双向字符。
"""

from __future__ import annotations

import re

# 来自内部可信数据源的工具，不需要注入防御
TRUSTED_TOOLS: frozenset[str] = frozenset({
    "knowledge",
})

# 沙箱定界符：ingested 内容里出现即视为逃逸尝试，中和其 `<`（&lt;）使其无法闭合我们的包裹标签
_SANDBOX_TAG_RE = re.compile(r"</?\s*tool_output", re.IGNORECASE)

# 注入模式（内联 (?i)/(?m) 旗标，全部 2-tuple）。flag-not-block：命中即打标记，不删内容。
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # ── 指令劫持（中英）──
    (r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", "ROLE_HIJACK"),
    (r"(?i)disregard\s+(your|the|all|previous|any)", "ROLE_HIJACK"),
    (r"(?i)forget\s+(everything|all|your|previous|the\s+above)", "ROLE_HIJACK"),
    (r"(?i)you\s+are\s+now\s+(a|an|the)?", "ROLE_HIJACK"),
    (r"忽略[^。！？\n]{0,8}(指令|命令|提示词?|规则|要求|限制)", "ROLE_HIJACK"),
    (r"忘记(你的|之前|所有|上述|前面)", "ROLE_HIJACK"),
    (r"(从现在起|现在开始|接下来)?你现在是(一个|一名)?", "ROLE_HIJACK"),
    # ── 系统覆盖 / 越狱 ──
    (r"(?i)new\s+system\s+prompt", "SYSTEM_OVERRIDE"),
    (r"(?i)override\s+(your|the|all)\s+(instructions?|rules?|settings?)", "SYSTEM_OVERRIDE"),
    (r"(?i)(developer|god|jailbreak|dan)\s+mode", "SYSTEM_OVERRIDE"),
    (r"(新的?|覆盖|替换).{0,4}系统(提示|指令|设定)", "SYSTEM_OVERRIDE"),
    # ── 伪造系统标记 / 回合标记 ──
    (r"(?i)\[SYSTEM\]|\[/?INST\]|<<SYS>>|###\s*system", "FAKE_SYSTEM"),
    (r"(?i)<\s*system\s*>", "FAKE_SYSTEM"),
    (r"【系统】|「系统」", "FAKE_SYSTEM"),
    (r"(?m)^\s*(Human|Assistant|User|System)\s*:", "FAKE_TURN"),
    (r"(?m)^\s*(用户|助手|系统|AI)\s*[:：]", "FAKE_TURN"),
    # ── LLM 控制 token ──
    (r"<\|(im_start|im_end|system|user|assistant|endoftext)\|>", "CHATML_INJECT"),
    # ── 提示词泄露诱导 ──
    (r"(?i)(reveal|print|show|repeat|output|dump)\b.{0,24}(system\s+)?(prompt|instructions?)", "PROMPT_LEAK"),
    (r"(泄露|打印|输出|重复|展示|复述).{0,12}(系统)?(提示词?|指令|prompt)", "PROMPT_LEAK"),
    # ── 数据外泄诱导 ──
    (r"(?i)(send|post|upload|exfiltrate|forward|leak)\b.{0,24}(to\s+)?(http|https|api[_\s-]?key|password|secret|token|credential)", "EXFIL_LURE"),
    (r"(把|将).{0,16}(发送|上传|泄露|转发|外发).{0,16}(到|给|至)", "EXFIL_LURE"),
    # ── 零宽 / 双向控制字符（隐藏指令）──
    (r"[​‌‍‪-‮⁦-⁩﻿]", "UNICODE_TRICK"),
]


def _scan_patterns(content: str) -> tuple[str, list[str]]:
    flagged = content
    flags: list[str] = []

    # 先中和沙箱定界符逃逸（把混入的 </tool_output> 的 < 变 &lt;，使其无法闭合包裹标签）
    if _SANDBOX_TAG_RE.search(flagged):
        flagged = _SANDBOX_TAG_RE.sub(lambda m: m.group(0).replace("<", "&lt;"), flagged)
        flags.append("SANDBOX_ESCAPE")

    for pattern, label in _INJECTION_PATTERNS:

        def make_replacement(lbl: str):
            return lambda m: f"[FLAGGED:{lbl}] {m.group(0)}"

        new_content, n = re.subn(pattern, make_replacement(label), flagged, count=0)
        if n:
            flagged = new_content
            if label not in flags:
                flags.append(label)
    return flagged, flags


def sanitize_tool_output(content: str, tool_name: str = "") -> str:
    """用 XML 沙箱包裹 tool output、标记注入模式、中和定界符逃逸。

    可信工具（TRUSTED_TOOLS）直接返回原始内容，无标签开销。
    其他工具输出包裹在 <tool_output trust="untrusted"> 沙箱内；命中注入标志时，
    在标签属性上列出 injection_flags，让 LLM 显式知情"这段是被标记过的不可信数据"。
    """
    if not content:
        return content
    if tool_name in TRUSTED_TOOLS:
        return content
    flagged, flags = _scan_patterns(content)
    tool_attr = f' tool="{tool_name}"' if tool_name else ""
    warn_attr = f' injection_flags="{",".join(flags)}"' if flags else ""
    return f'<tool_output{tool_attr} trust="untrusted"{warn_attr}>\n{flagged}\n</tool_output>'


def injection_flags(content: str, tool_name: str = "") -> list[str]:
    """返回内容中检测到的注入标志列表（可信工具直接返回空列表）。"""
    if tool_name in TRUSTED_TOOLS:
        return []
    _, flags = _scan_patterns(content)
    return flags
