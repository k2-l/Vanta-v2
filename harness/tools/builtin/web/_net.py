"""联网工具共用底座：出站 URL 安全校验（SSRF 前置）+ HTML→纯文本抽取。

WebFetch/WebSearch 在 harness 进程内直接发出站 HTTP，安全重心是 SSRF——防止被
（可能来自被抓取网页的）注入指令诱导去打内网/回环地址。这里做尽力而为的字面量层
校验；真正的出站边界仍应由部署网络策略兜底。
"""

from __future__ import annotations

import html as _html
import ipaddress
import re
from urllib.parse import urlparse

# 放行的协议
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# 常见本地/内网主机名（非 IP 字面量）
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def safe_public_url(url: str) -> tuple[bool, str]:
    """尽力而为的 SSRF 前置校验（仅字面量层面，不做 DNS 解析）。

    返回 (是否放行, 拒绝原因)。放行时原因为空串。
    按主机字面量拦回环/私有/链路本地地址；DNS 重绑定等高级绕过不在 v1 目标内。
    """
    try:
        p = urlparse(url.strip())
    except Exception:  # noqa: BLE001
        return False, "URL 解析失败"

    if p.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"只允许 http/https，收到：{p.scheme or '(空)'}"

    host = (p.hostname or "").lower()
    if not host:
        return False, "URL 缺少主机名"
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        return False, "禁止访问本地地址"

    # 字面 IP → 拦回环/私有/保留段
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False, f"禁止访问非公网地址：{host}"

    return True, ""


# ── HTML → 纯文本：去 script/style/注释/head，块级标签转换行，剥标签，反转义，压空白 ──
_RE_SCRIPT_STYLE = re.compile(r"(?is)<(script|style|noscript|template)\b.*?</\1>")
_RE_COMMENT = re.compile(r"(?s)<!--.*?-->")
_RE_HEAD = re.compile(r"(?is)<head\b.*?</head>")
_RE_BLOCK = re.compile(
    r"(?i)</?(?:p|div|section|article|header|footer|nav|main|li|ul|ol|tr|td|th|table"
    r"|h[1-6]|br|blockquote|pre)\s*/?>"
)
_RE_TAG = re.compile(r"(?s)<[^>]+>")
_RE_HSPACE = re.compile(r"[ \t\f\v]+")
_RE_BLANKS = re.compile(r"\n{3,}")


def html_to_text(html_src: str) -> str:
    """把（可能很脏的）HTML 粗略转成可读纯文本。无第三方依赖，尽力而为。"""
    if not html_src:
        return ""
    s = _RE_SCRIPT_STYLE.sub(" ", html_src)
    s = _RE_COMMENT.sub(" ", s)
    s = _RE_HEAD.sub(" ", s)
    s = _RE_BLOCK.sub("\n", s)
    s = _RE_TAG.sub(" ", s)
    s = _html.unescape(s)
    lines = [_RE_HSPACE.sub(" ", ln).strip() for ln in s.split("\n")]
    s = _RE_BLANKS.sub("\n\n", "\n".join(lines))
    return s.strip()
