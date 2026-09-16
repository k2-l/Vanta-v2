"""URL 内容抓取 — article（通用 HTML）/ github（REST API + README）。

抓取结果统一为 {"title", "content", "meta"}：
  - article：GET 原始 HTML，截断到 _MAX_CONTENT_CHARS，交给 LLM 自行容忍脏标签。
  - github：解析 owner/repo，调 GitHub REST `/repos/{o}/{r}` 取 stars/language/topics/
    description 进 meta，再调 `/readme` 取正文（base64 解码）。匿名访问；若配置
    settings.github_token 则带 Authorization 头提升限流额度。

source_type 嗅探：URL 含 "github.com" → github，否则 article。
"""

from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from harness.infra.logging import log
from harness.infra.retry import with_retry
from harness.infra.settings import get_settings

_HTTP_TIMEOUT = 15.0
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2MB
_MAX_CONTENT_CHARS = 32_000        # 截断长度，喂给 LLM（不引抽取依赖，容忍脏 HTML）
_USER_AGENT = "Mozilla/5.0 (compatible; Vanta/1.0; +https://github.com/)"

_GITHUB_API = "https://api.github.com"


class _PinnedTransport(httpx.AsyncBaseTransport):
    """把已校验域名固定连接到指定 IP，同时保留原 Host 与 HTTPS SNI。"""

    def __init__(self, hostname: str, address: str) -> None:
        self._hostname = hostname.lower()
        self._address = address
        # 禁用环境代理，避免代理端重新解析用户域名而绕过固定地址。
        self._inner = httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.lower() != self._hostname:
            raise ValueError("固定传输层拒绝访问未校验的主机")
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = self._hostname
        pinned_request = httpx.Request(
            method=request.method,
            url=request.url.copy_with(host=self._address),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def sniff_source_type(url: str) -> str:
    """URL 含 github.com → "github"，否则 "article"。解析失败 → "unknown"。"""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return "unknown"
    if not host:
        return "unknown"
    if "github.com" in host:
        return "github"
    return "article"


def _truncate(text: str, limit: int = _MAX_CONTENT_CHARS) -> str:
    return text[:limit] if len(text) > limit else text


def _extract_title_from_html(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:500]


def _parse_github_owner_repo(url: str) -> tuple[str, str] | None:
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    repo = re.sub(r"\.git$", "", repo)
    return owner, repo


@with_retry
async def _http_get(client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    resp = await client.get(url, **kwargs)
    resp.raise_for_status()
    return resp


async def _fetch_article(url: str, resolved_ips: tuple[str, ...]) -> dict[str, Any]:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname or not resolved_ips:
        raise ValueError("网页抓取缺少已校验的固定公网地址")
    headers = {"User-Agent": _USER_AGENT}
    transport = _PinnedTransport(hostname, resolved_ips[0])
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=False,
        transport=transport,
    ) as client:
        resp = await _http_get(client, url, headers=headers)
        if resp.is_redirect:
            raise ValueError("为防止 SSRF，通用网页抓取不允许 HTTP 重定向")
        body = resp.content[:_MAX_BODY_BYTES]
        html = body.decode(resp.encoding or "utf-8", errors="replace")

    title = _extract_title_from_html(html)
    return {
        "title": title,
        "content": _truncate(html),
        "meta": {
            "status_code": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "final_url": url,
        },
    }


async def _fetch_github(url: str) -> dict[str, Any]:
    parsed = _parse_github_owner_repo(url)
    if parsed is None:
        raise ValueError(f"无法从 URL 解析 owner/repo：{url}")
    owner, repo = parsed

    s = get_settings()
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    if s.github_token:
        headers["Authorization"] = f"token {s.github_token}"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        repo_resp = await _http_get(client, f"{_GITHUB_API}/repos/{owner}/{repo}", headers=headers)
        repo_data = repo_resp.json()

        readme_content = ""
        try:
            readme_resp = await _http_get(
                client, f"{_GITHUB_API}/repos/{owner}/{repo}/readme", headers=headers
            )
            readme_data = readme_resp.json()
            raw = readme_data.get("content", "")
            if raw:
                readme_content = base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            log.warning("fetcher.github_readme_failed", owner=owner, repo=repo, exc=str(exc)[:200])

    meta = {
        "owner": owner,
        "repo": repo,
        "stars": repo_data.get("stargazers_count", 0),
        "language": repo_data.get("language") or "",
        "topics": repo_data.get("topics", []),
        "description": repo_data.get("description") or "",
        "html_url": repo_data.get("html_url", url),
    }
    title = repo_data.get("full_name") or f"{owner}/{repo}"
    return {
        "title": title,
        "content": _truncate(readme_content or meta["description"]),
        "meta": meta,
    }


async def fetch(
    url: str,
    source_type: str,
    *,
    resolved_ips: tuple[str, ...] = (),
) -> dict[str, Any]:
    """抓取 url，返回 {"title", "content", "meta"}。

    source_type 为 "github" 时走 GitHub REST API，否则按通用 article 抓 HTML。
    调用方负责捕获异常并落 status=failed + error 字段。
    """
    if source_type == "github":
        return await _fetch_github(url)
    return await _fetch_article(url, resolved_ips)
