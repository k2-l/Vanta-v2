"""per-engagement 网络隔离沙箱：把 scope 落到物理网络出站强制。

安全模型：**网络出站边界 = 唯一强 scope 控制**。四部分：
  1. resolve_scope_to_ips —— harness 侧把 scope 域名解析成 IP，只喂 IP 给沙箱（杜绝沙箱内 DNS 绕过）。
  2. build_nft_ruleset    —— 生成 nft 脚本：默认 DROP ip+ip6 OUTPUT，仅放行 loopback/established/scope。
  3. build_entrypoint     —— 入口脚本：装规则 → fail-closed 自检 → 丢弃 NET_ADMIN → exec 工具。
  4. SandboxManager       —— podman 起停 / exec / teardown（需 harness 具备 podman 访问）。

纯函数 1–3 无副作用、可独立单测；4 需 harness→podman 通路。
"""

from __future__ import annotations

import asyncio
import ipaddress
import shlex
import socket
from dataclasses import dataclass, field

from harness.infra.logging import log
from harness.security.engagement import classify_scope_entry

# 已知稳定的"公网 scope 外"探针（fail-closed 自检用；1.1.1.1 —— 不在任何真实 engagement scope 内）
DEFAULT_PROBE_IP = "1.1.1.1"
DEFAULT_PROBE_PORT = 443
_SELFCHECK_TIMEOUT = 4
_SANDBOX_NFT_PATH = "/etc/vanta_egress.nft"

# 活跃沙箱登记表（0.9 急停 / engagement 收尾用）：engagement_id → SandboxManager
_ACTIVE: dict[str, SandboxManager] = {}


# ── 1. scope → IP allowlist（harness 侧解析）────────────────────────────
def resolve_scope_to_ips(scope_targets: list[str]) -> tuple[set[str], set[str]]:
    """把 scope 清单解析成 (单 IP 集, CIDR 集)，供 nft allowlist。

    - ip / cidr → 直接进对应集合。
    - domain → getaddrinfo 解析出的全部 A/AAAA 进 IP 集。
    - domain_wildcard(`*.x`) → 解析 base 域名 `x` 作起点（子域的运行时 IP 由 recon
      发现后动态追加，属后续 allowlist-update；此处不枚举）。
    - repo → 跳过（代码审计用途，非网络目标）。

    DNS 解析只发生在 **harness 侧**；沙箱内不做 DNS（见 build_nft_ruleset）。
    """
    ips: set[str] = set()
    cidrs: set[str] = set()
    for entry in scope_targets:
        kind = classify_scope_entry(entry)
        e = entry.strip()
        if kind == "ip":
            ips.add(e)
        elif kind == "cidr":
            cidrs.add(str(ipaddress.ip_network(e, strict=False)))
        elif kind in ("domain", "domain_wildcard"):
            host = e[2:] if kind == "domain_wildcard" else e
            for ip in _resolve_host(host):
                ips.add(ip)
        # repo / invalid → skip
    return ips, cidrs


def _resolve_host(host: str) -> set[str]:
    """getaddrinfo 解析主机的全部 A/AAAA，失败返回空集（不抛，交由 fail-closed 兜底）。"""
    out: set[str] = set()
    try:
        for fam, _t, _p, _c, sockaddr in socket.getaddrinfo(host, None):
            if fam in (socket.AF_INET, socket.AF_INET6):
                out.add(sockaddr[0].split("%")[0])  # 去掉 IPv6 zone-id
    except (OSError, socket.gaierror) as exc:
        log.warning("sandbox.resolve_failed", host=host, exc=str(exc)[:120])
    return out


# ── 2. nft 出站规则生成 ─────────────────────────────────────────────────
def _split_families(items: set[str]) -> tuple[list[str], list[str]]:
    """把 IP/CIDR 字符串按 v4/v6 分组（非法项丢弃）。返回 (v4_sorted, v6_sorted)。"""
    v4: list[str] = []
    v6: list[str] = []
    for item in items:
        try:
            ver = ipaddress.ip_network(item, strict=False).version if "/" in item else ipaddress.ip_address(item).version
        except ValueError:
            continue
        (v4 if ver == 4 else v6).append(item)
    return sorted(v4), sorted(v6)


def build_nft_ruleset(
    allow_ips: set[str],
    allow_cidrs: set[str],
    dns_resolver_ip: str | None = None,
) -> str:
    """生成 nft 脚本：默认 DROP `ip`+`ip6` OUTPUT，仅放行 loopback/established/scope。

    - **双栈都锁**：单一 inet 表 + policy drop 同时覆盖 IPv4 与 IPv6（防 IPv6 直连绕过）。
    - **默认不放行任何 DNS**（沙箱不自解析）；仅当给了受控 resolver 才放行到它的 53。
    - 空 allowlist = 纯零出站（合法：fail-closed）。
    """
    v4, v6 = _split_families(allow_ips | allow_cidrs)
    lines = [
        "flush ruleset",
        "",
        "table inet vanta_egress {",
        "\tchain output {",
        "\t\ttype filter hook output priority 0; policy drop;",
        "",
        '\t\toifname "lo" accept',
        "\t\tct state established,related accept",
    ]
    if dns_resolver_ip:
        try:
            resolver = ipaddress.ip_address(dns_resolver_ip)
            fam = "ip" if resolver.version == 4 else "ip6"
            lines.append(f"\t\t{fam} daddr {resolver} udp dport 53 accept")
            lines.append(f"\t\t{fam} daddr {resolver} tcp dport 53 accept")
        except ValueError:
            log.warning("sandbox.bad_resolver", resolver=dns_resolver_ip)
    if v4:
        lines.append(f"\t\tip daddr {{ {', '.join(v4)} }} accept")
    if v6:
        lines.append(f"\t\tip6 daddr {{ {', '.join(v6)} }} accept")
    lines += ["\t}", "}", ""]
    return "\n".join(lines)


# ── 3. 沙箱入口脚本（装规则 → 自检 → 丢 cap → exec）─────────────────────
def build_entrypoint(
    tool_argv: list[str],
    *,
    probe_ip: str = DEFAULT_PROBE_IP,
    probe_port: int = DEFAULT_PROBE_PORT,
) -> str:
    """生成沙箱入口 sh 脚本：先装 nft 规则（外部已写入 {_SANDBOX_NFT_PATH}），
    再做 fail-closed 自检（探 scope 外 IP 必须被拦），确认锁死后**丢弃 NET_ADMIN**
    再 exec 工具。任一步失败 → 非零退出、绝不跑工具。
    """
    tool_cmd = " ".join(shlex.quote(a) for a in tool_argv)
    # 自检用 python3 heredoc（沙箱镜像自带 python3），避免内联引号地狱
    return f"""#!/bin/sh
set -eu

# 1) 装出站规则（默认 DROP + 仅 scope）
nft -f {_SANDBOX_NFT_PATH}

# 2) fail-closed 自检：探一个 scope 外 IP，必须连不上；连上=规则没生效=abort
if python3 - <<'PYCHK'
import socket, sys
socket.setdefaulttimeout({_SELFCHECK_TIMEOUT})
try:
    socket.create_connection(("{probe_ip}", {probe_port}))
    sys.exit(0)          # 连上了 = 出站未锁
except Exception:
    sys.exit(1)          # 连不上 = 已锁死（期望）
PYCHK
then
    echo "[sandbox] SELFCHECK_FAIL: egress not locked (reached {probe_ip})" >&2
    exit 99
fi

# 3) 丢弃 NET_ADMIN + SETPCAP 后再跑工具（工具无权改防火墙、无权改自身 cap；保留 NET_RAW 供 nmap）
exec capsh --drop=cap_net_admin,cap_setpcap -- -c {shlex.quote(tool_cmd)}
"""


# ── 4. 沙箱编排（podman）─────────────────────────────────────────────────
@dataclass
class SandboxSpec:
    engagement_id: str
    image: str = "vanta-sandbox"
    allow_ips: set[str] = field(default_factory=set)
    allow_cidrs: set[str] = field(default_factory=set)
    dns_resolver_ip: str | None = None


class SandboxManager:
    """per-engagement podman 沙箱的起停 / exec / teardown。

    注意：harness 进程需具备 podman 访问（socket 挂载，见 dev-up.sh harness 段）才能 E2E；
    本类负责编排逻辑与命令构造，实际 podman 调用走 asyncio 子进程。
    """

    def __init__(self, spec: SandboxSpec) -> None:
        self.spec = spec
        self.container = f"vanta-sbx-{spec.engagement_id}"

    def create_argv(self) -> list[str]:
        """构造 podman run 参数（纯函数）：一次性容器、最小 cap、后台常驻。"""
        return [
            "podman", "run", "-d", "--replace", "--name", self.container,
            # NET_ADMIN(nft) + NET_RAW(nmap 原始包) + SETPCAP(capsh 丢弃 bounding cap 需要)
            "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW", "--cap-add", "SETPCAP",
            "--security-opt", "no-new-privileges",
            self.spec.image, "sleep", "infinity",
        ]

    async def _podman(self, *args: str, stdin: str | None = None, timeout: float = 30) -> tuple[int, str, str]:  # noqa: ASYNC109 — 子进程超时透传，与 shell.py/tool_exec.py 同款
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin is not None else None), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, "", f"podman timeout(>{timeout}s)"
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def start(self) -> None:
        """起沙箱容器 + 写入 nft 规则文件（供入口/exec 时 nft -f 装载）。"""
        rc, _out, err = await self._podman(*self.create_argv())
        if rc != 0:
            raise RuntimeError(f"沙箱启动失败：{err[:300]}")
        ruleset = build_nft_ruleset(self.spec.allow_ips, self.spec.allow_cidrs, self.spec.dns_resolver_ip)
        rc, _o, err = await self._podman(
            "podman", "exec", "-i", self.container, "sh", "-c", f"cat > {_SANDBOX_NFT_PATH}", stdin=ruleset
        )
        if rc != 0:
            raise RuntimeError(f"写入 nft 规则失败：{err[:300]}")
        _ACTIVE[self.spec.engagement_id] = self
        log.info("sandbox.started", engagement=self.spec.engagement_id, ips=len(self.spec.allow_ips))

    async def run_tool(self, tool_argv: list[str], timeout: float = 60) -> tuple[int, str, str]:  # noqa: ASYNC109 — 沙箱工具执行超时透传
        """在沙箱内经入口脚本跑一条工具命令（装规则 → 自检 → 丢 cap → exec）。"""
        entry = build_entrypoint(tool_argv)
        return await self._podman("podman", "exec", "-i", self.container, "sh", "-c", entry, timeout=timeout)

    async def teardown(self) -> None:
        """拆沙箱（kill switch / engagement 收尾）。幂等。"""
        _ACTIVE.pop(self.spec.engagement_id, None)
        await self._podman("podman", "rm", "-f", self.container, timeout=15)
        log.info("sandbox.torn_down", engagement=self.spec.engagement_id)


# ── 0.9 全局急停 / engagement 收尾 ──────────────────────────────────────
def active_engagements() -> list[str]:
    """当前有活跃沙箱的 engagement 列表。"""
    return list(_ACTIVE.keys())


async def teardown_engagement(engagement_id: str) -> bool:
    """拆某 engagement 的沙箱（engagement 结束/过期收尾用）。无则返回 False。"""
    manager = _ACTIVE.get(engagement_id)
    if manager is None:
        return False
    await manager.teardown()
    return True


async def teardown_all() -> int:
    """全局急停（kill switch）：拆掉所有活跃沙箱。返回拆掉数量。单个失败不中断其余。"""
    managers = list(_ACTIVE.values())
    for manager in managers:
        try:
            await manager.teardown()
        except Exception as exc:  # noqa: BLE001 —— 急停尽力拆全部，单个失败不阻断
            log.warning(
                "sandbox.teardown_failed", engagement=manager.spec.engagement_id, exc=str(exc)[:200]
            )
    _ACTIVE.clear()
    return len(managers)


async def get_or_create_sandbox(
    engagement_id: str,
    scope_targets: tuple[str, ...] | list[str],
    dns_resolver_ip: str = "",
) -> SandboxManager:
    """取该 engagement 的活跃沙箱，或按 scope 新建并启动（含 nft 规则写入）。

    scope 域名在此（harness 侧）解析成 IP 灌进沙箱 nft allowlist；沙箱内不做 DNS。
    """
    manager = _ACTIVE.get(engagement_id)
    if manager is not None:
        return manager
    allow_ips, allow_cidrs = resolve_scope_to_ips(list(scope_targets))
    spec = SandboxSpec(
        engagement_id=engagement_id,
        allow_ips=allow_ips,
        allow_cidrs=allow_cidrs,
        dns_resolver_ip=dns_resolver_ip or None,
    )
    manager = SandboxManager(spec)
    await manager.start()  # 起容器 + 写 nft 规则 + 注册进 _ACTIVE
    return manager
