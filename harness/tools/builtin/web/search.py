"""WebSearch 工具：联网搜索，返回 标题 + URL + 摘要 列表。

后端可插拔（settings.search_provider）：
  - duckduckgo（默认，无需 key）：抓 DuckDuckGo HTML SERP 解析结果；
  - tavily（需 search_api_key）：LLM 友好的检索 API，摘要更干净。
无 key 源可能被目标站限流/拦截；失败时回落到清晰报错，提示配置 search_api_key。
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from harness.infra.retry import with_retry
from harness.infra.settings import get_settings
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register

_HTTP_TIMEOUT = 15.0
# DDG 会把非浏览器 UA 判为机器人、返回空结果页，故用真实浏览器 UA
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_MAX_RESULTS = 5
_HARD_MAX_RESULTS = 10


@with_retry
async def _post(client: httpx.AsyncClient, url: str, **kw: Any) -> httpx.Response:
    resp = await client.post(url, **kw)
    resp.raise_for_status()
    return resp


# ── DuckDuckGo HTML SERP（无 key）────────────────────────────────
# 属性顺序无关：先框住带 result__a 的 <a> 整块，再从其属性串里抠 href
_RE_DDG_RESULT = re.compile(
    r'<a\b(?P<attrs>[^>]*\bclass="result__a"[^>]*)>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_RE_DDG_SNIPPET = re.compile(
    r'<a\b[^>]*\bclass="result__snippet"[^>]*>(?P<snip>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_RE_HREF = re.compile(r'href="(?P<href>[^"]+)"', re.IGNORECASE)
_RE_TAGS = re.compile(r"(?s)<[^>]+>")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(_RE_TAGS.sub("", s or ""))).strip()


def _ddg_real_url(href: str) -> str:
    """DDG 结果链接常是 //duckduckgo.com/l/?uddg=<编码真实URL> 的跳板，解出真实 URL。"""
    try:
        full = href if href.startswith("http") else f"https:{href}"
        p = urlparse(full)
        if "duckduckgo.com" in p.netloc and p.path.startswith("/l/"):
            uddg = parse_qs(p.query).get("uddg")
            if uddg:
                return uddg[0]
        return full
    except Exception:  # noqa: BLE001
        return href


async def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    headers = {
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = await _post(
            client,
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "wt-wt"},
            headers=headers,
        )
        html = resp.text

    matches = list(_RE_DDG_RESULT.finditer(html))
    snippets = _RE_DDG_SNIPPET.findall(html)
    out: list[dict[str, str]] = []
    for i, m in enumerate(matches[:max_results]):
        href_m = _RE_HREF.search(m.group("attrs"))
        if not href_m:
            continue
        out.append(
            {
                "title": _clean(m.group("title")),
                "url": _ddg_real_url(href_m.group("href")),
                "snippet": _clean(snippets[i]) if i < len(snippets) else "",
            }
        )
    return out


# ── Tavily（需 key，LLM 友好）──────────────────────────────────
async def _search_tavily(
    query: str, max_results: int, api_key: str, base_url: str
) -> list[dict[str, str]]:
    endpoint = (base_url or "https://api.tavily.com").rstrip("/") + "/search"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await _post(
            client,
            endpoint,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        data = resp.json()

    out: list[dict[str, str]] = []
    for r in (data.get("results") or [])[:max_results]:
        out.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": r.get("url") or "",
                "snippet": (r.get("content") or "").strip(),
            }
        )
    return out


@register
class WebSearchTool(Tool):
    name = "WebSearch"
    category = "web"
    description = (
        "联网搜索，返回若干条 标题 + URL + 摘要。\n"
        "拿到 URL 后可用 WebFetch 读取网页全文。\n"
        "默认走免费 DuckDuckGo；配置 search_api_key 后可切 Tavily 等更稳的检索 API。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或自然语言查询",
            },
            "max_results": {
                "type": "integer",
                "description": f"返回结果条数，默认 {_DEFAULT_MAX_RESULTS}",
                "default": _DEFAULT_MAX_RESULTS,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str = "", max_results: int = _DEFAULT_MAX_RESULTS) -> ToolResult:
        query = (query or "").strip()
        if not query:
            return ToolResult.fail(error="缺少 query", error_code="INVALID_ARGS")
        n = max(1, min(int(max_results or _DEFAULT_MAX_RESULTS), _HARD_MAX_RESULTS))

        settings = get_settings()
        provider = (settings.search_provider or "duckduckgo").lower()
        try:
            if provider == "tavily":
                if not settings.search_api_key:
                    return ToolResult.fail(
                        error="search_provider=tavily 但未配置 search_api_key",
                        error_code="CONFIG_ERROR",
                    )
                results = await _search_tavily(query, n, settings.search_api_key, settings.search_base_url)
            else:
                results = await _search_duckduckgo(query, n)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                error=(
                    f"搜索失败（{provider}）：{type(exc).__name__}: {str(exc)[:200]}。"
                    "若持续失败，可在 data/config.toml [search] 配置 provider=tavily + api_key。"
                ),
                error_code="SEARCH_FAILED",
            )

        if not results:
            hint = ""
            if provider != "tavily":
                hint = (
                    "（DuckDuckGo 免费源可能被限流/临时拦截；如需稳定检索，"
                    "在 data/config.toml [search] 配置 provider=tavily + api_key）"
                )
            return ToolResult(ok=True, output=f"未搜到与「{query}」相关的结果。{hint}")

        lines = [f"「{query}」搜索到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            snip = r["snippet"][:200]
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {snip}")
        lines.append("\n→ 需要正文时用 WebFetch(url=...) 读取。")
        return ToolResult(ok=True, output="\n".join(lines))
