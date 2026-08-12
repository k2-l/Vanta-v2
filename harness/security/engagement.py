"""Engagement / Scope —— 授权范围的纯逻辑（scope 匹配 + RoE 有效期），不碰 DB、可独立单测。

scope 授权边界是本平台安全核心：主动动作前用 target_in_scope() + is_engagement_active()
双重校验；网络出站层(sandbox)再按解析出的 IP 兜底强制（纵深防御，二者不互替）。
持久化模型见 db.py(EngagementRecord)，出站强制见 sandbox.py。
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# 单个 DNS label 的合法形态（RFC 1035 宽松版）
_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")

# scope 条目类型
_KIND_IP = "ip"
_KIND_CIDR = "cidr"
_KIND_DOMAIN = "domain"
_KIND_DOMAIN_WILDCARD = "domain_wildcard"
_KIND_REPO = "repo"
_KIND_INVALID = "invalid"


def _looks_like_domain(s: str) -> bool:
    """粗判是否为域名：至少两段 label、每段合法、总长 ≤253。"""
    s = s.strip().rstrip(".")
    if not s or len(s) > 253 or "/" in s or " " in s:
        return False
    labels = s.split(".")
    if len(labels) < 2:  # 要求 a.b，避免把裸主机名/单词当 scope
        return False
    return all(_LABEL_RE.fullmatch(lb) for lb in labels)


def classify_scope_entry(entry: str) -> str:
    """判定一条 scope 条目类型：ip | cidr | domain | domain_wildcard | repo | invalid。"""
    e = (entry or "").strip()
    if not e:
        return _KIND_INVALID
    if e.startswith("repo:"):
        return _KIND_REPO
    if "/" in e:  # CIDR
        try:
            ipaddress.ip_network(e, strict=False)
            return _KIND_CIDR
        except ValueError:
            return _KIND_INVALID
    try:  # 纯 IP
        ipaddress.ip_address(e)
        return _KIND_IP
    except ValueError:
        pass
    if e.startswith("*."):  # 通配域名
        return _KIND_DOMAIN_WILDCARD if _looks_like_domain(e[2:]) else _KIND_INVALID
    return _KIND_DOMAIN if _looks_like_domain(e) else _KIND_INVALID


def normalize_host(target: str) -> str:
    """把目标归一为纯主机：去 scheme / userinfo / 端口 / 路径，小写、去尾点。

    容忍 `https://a.b:443/x?y`、`user@host:22`、`[2001:db8::1]:80`、裸 IPv6 等形态。
    """
    host = (target or "").strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0]  # 去 path/query
    if "@" in host:  # 去 userinfo
        host = host.rsplit("@", 1)[1]
    if host.startswith("[") and "]" in host:  # [IPv6]:port
        host = host[1 : host.index("]")]
    elif host.count(":") == 1:  # host:port（IPv4/域名；裸 IPv6 有多个冒号，不误伤）
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def target_in_scope(target: str, scope_targets: list[str]) -> bool:
    """target（域名或 IP，容忍带 scheme/端口/路径）是否落在 scope 内。

    匹配规则（保守、显式，避免意外越权）：
    - 目标是 IP → 命中 ip 精确 或 cidr 包含。
    - 目标是域名 → 命中 domain 精确；或 domain_wildcard(`*.x`) 匹配其子域
      （**不含 apex**，除非 apex 单列）。
    repo 条目不参与网络目标匹配（代码审计用途，另行处理）。
    """
    host = normalize_host(target)
    if not host:
        return False

    tip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        tip = ipaddress.ip_address(host)
    except ValueError:
        pass

    for entry in scope_targets:
        kind = classify_scope_entry(entry)
        e = entry.strip()
        if tip is not None:
            if kind == _KIND_IP and ipaddress.ip_address(e) == tip:
                return True
            if kind == _KIND_CIDR and tip in ipaddress.ip_network(e, strict=False):
                return True
        else:
            el = e.lower().rstrip(".")
            if kind == _KIND_DOMAIN and host == el:
                return True
            if kind == _KIND_DOMAIN_WILDCARD:
                base = el[2:]  # 去 "*."；通配只匹配子域，不含 apex（apex 需单列，避免越权）
                if host.endswith("." + base):
                    return True
    return False


def validate_scope(scope_targets: list[str]) -> tuple[list[str], list[str]]:
    """把 scope 清单分成 (valid, invalid)；空/非法条目进 invalid。"""
    valid: list[str] = []
    invalid: list[str] = []
    for e in scope_targets:
        (invalid if classify_scope_entry(e) == _KIND_INVALID else valid).append((e or "").strip())
    return valid, invalid


@dataclass
class Engagement:
    """内存态 engagement（DB 记录映射到此做逻辑判定；纯逻辑不碰 DB）。"""

    id: str
    name: str
    scope_targets: list[str] = field(default_factory=list)
    status: str = "draft"          # draft | active | ended
    authorization_ref: str = ""     # 授权书 / CTF 规则 / scope 批准引用（激活前置硬门）
    starts_at: datetime | None = None
    ends_at: datetime | None = None


def is_engagement_active(eng: Engagement, now: datetime | None = None) -> tuple[bool, str]:
    """engagement 当前是否允许主动动作（scope 门前置校验）。返回 (ok, 原因)。"""
    now = now or datetime.now(UTC)
    if eng.status != "active":
        return False, f"engagement 状态为 {eng.status}（非 active）"
    if not eng.authorization_ref.strip():
        return False, "缺少授权凭证引用（authorization_ref），拒绝激活"
    if eng.starts_at and now < eng.starts_at:
        return False, "engagement 尚未到生效时间（RoE 时间窗）"
    if eng.ends_at and now > eng.ends_at:
        return False, "engagement 已过 RoE 有效期"
    return True, "active"
