"""WebFetch 工具：抓取一个 URL 并返回可读正文。

复用 infra/fetcher 的抓取（article 走通用 HTML、github 走 REST API + README）；
article 抓回来的是原始 HTML，这里再过一层 html_to_text 转纯文本，省 token、易读。
"""

from __future__ import annotations

from typing import Any

from harness.infra import fetcher
from harness.tools.base import Tool, ToolResult
from harness.tools.builtin.web._net import html_to_text, safe_public_url
from harness.tools.registry import register

_DEFAULT_MAX_CHARS = 8_000
_HARD_MAX_CHARS = 20_000


@register
class WebFetchTool(Tool):
    name = "WebFetch"
    category = "web"
    description = (
        "抓取一个网页/URL 并返回可读正文。\n"
        "- 普通网页：GET HTML 后转成纯文本；\n"
        "- GitHub 仓库地址：走 GitHub API，返回 stars/语言/描述 + README。\n"
        "常配合 WebSearch：先搜到 URL，再用本工具读取。仅支持 http/https 公网地址。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的网页地址（http/https）",
            },
            "max_chars": {
                "type": "integer",
                "description": f"返回正文最大字符数，默认 {_DEFAULT_MAX_CHARS}",
                "default": _DEFAULT_MAX_CHARS,
            },
        },
        "required": ["url"],
    }

    async def run(self, url: str = "", max_chars: int = _DEFAULT_MAX_CHARS) -> ToolResult:
        url = (url or "").strip()
        if not url:
            return ToolResult.fail(error="缺少 url", error_code="INVALID_ARGS")

        ok, reason = safe_public_url(url)
        if not ok:
            return ToolResult.fail(
                error=f"URL 未通过安全校验：{reason}", error_code="PERMISSION_DENIED"
            )

        limit = max(500, min(int(max_chars or _DEFAULT_MAX_CHARS), _HARD_MAX_CHARS))
        source_type = fetcher.sniff_source_type(url)
        try:
            result = await fetcher.fetch(url, source_type)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                error=f"抓取失败（{source_type}）：{type(exc).__name__}: {str(exc)[:300]}",
                error_code="FETCH_FAILED",
            )

        title = (result.get("title") or "").strip()
        content = result.get("content") or ""
        meta = result.get("meta") or {}

        # article 抓回来的是原始 HTML → 转纯文本；github 已是 README markdown，原样保留
        if source_type == "article":
            content = html_to_text(content)

        final_url = meta.get("final_url") or meta.get("html_url") or url
        body = content.strip()
        if len(body) > limit:
            body = body[:limit] + f"\n\n[... 已截断，正文原长 {len(content)} 字符 ...]"

        header_lines = []
        if title:
            header_lines.append(f"# {title}")
        header_lines.append(f"URL: {final_url}")
        if source_type == "github":
            gh = f"★ {meta.get('stars', 0)} · {meta.get('language') or '—'}"
            if meta.get("description"):
                gh += f" · {meta['description']}"
            header_lines.append(gh)
        header = "\n".join(header_lines)

        if not body:
            return ToolResult(ok=True, output=f"{header}\n\n（未抽取到正文内容）")
        return ToolResult(ok=True, output=f"{header}\n\n{body}")
