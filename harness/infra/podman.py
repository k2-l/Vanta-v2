"""podman CLI 封装 —— 容器管理（原 nexus-svc services/podman.go 端口）。

harness 容器内自带 podman CLI + 挂宿主 podman socket（CONTAINER_HOST，见 dev-up.sh），
故直接 shell 出去调 `podman`，与 security/sandbox.py 同款（不引 docker/podman SDK 依赖）。
命令构造为纯参数、调用走 asyncio 子进程；异常统一转 RuntimeError 交由调用方兜底。
"""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass

from harness.infra.logging import log

_START_TIMEOUT = 120
_EGRESS_PROBE_URL = "https://example.com/"


@dataclass
class ContainerSummary:
    """daemon 视角的一个 live 容器（运行或已停）。"""
    id: str
    name: str
    image: str
    state: str   # running | exited | created | ...


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class RuntimeReadiness:
    ready: bool
    reason: str
    network_mode: str = ""
    network_access: str = "not_checked"  # not_checked | disabled | available | unavailable


async def probe_network_egress(container_id: str) -> ExecResult:
    """Verify usable HTTPS egress from inside the container with a fixed safe target.

    Try common runtimes in order so an image does not have to carry curl specifically.
    This is deliberately an actual request rather than trusting Podman's network mode.
    """
    command = (
        "if command -v curl >/dev/null 2>&1; then "
        f"curl -fsS --connect-timeout 5 --max-time 10 {_EGRESS_PROBE_URL} >/dev/null; "
        "elif command -v wget >/dev/null 2>&1; then "
        f"wget -q -T 10 -O /dev/null {_EGRESS_PROBE_URL}; "
        "elif command -v python3 >/dev/null 2>&1; then "
        f"python3 -c \"import urllib.request; urllib.request.urlopen('{_EGRESS_PROBE_URL}', timeout=10).read(1)\"; "
        "elif command -v node >/dev/null 2>&1; then "
        f"node -e \"fetch('{_EGRESS_PROBE_URL}', {{signal: AbortSignal.timeout(10000)}})"
        ".then(r => process.exit(r.ok ? 0 : 2)).catch(() => process.exit(3))\"; "
        "else echo '缺少 curl、wget、python3 或 node，无法验证 HTTPS 出网' >&2; exit 127; fi"
    )
    return await exec(container_id, ["sh", "-c", command], timeout=15)


async def _podman(*args: str, stdin: str | None = None, timeout: float = 30) -> tuple[int, str, str]:  # noqa: ASYNC109 — 子进程超时透传，与 security/sandbox.py 同款
    """跑一条 `podman <args>`，返回 (rc, stdout, stderr)。超时 → rc=124。"""
    proc = await asyncio.create_subprocess_exec(
        "podman", *args,
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


def normalize_state(state: str) -> str:
    """把 podman/daemon 的 state 归一成 created|running|stopped（对齐 nexus normalizeState）。"""
    s = (state or "").lower()
    if s == "running":
        return "running"
    if s in ("created", "configured", "initialized"):
        return "created"
    return "stopped"   # exited / dead / paused / removing ...


async def ping() -> bool:
    """podman daemon 是否可达。"""
    rc, _o, _e = await _podman("info", "--format", "{{.Host.Arch}}", timeout=10)
    return rc == 0


async def is_running(container_id: str) -> bool:
    """Return the daemon's live running state instead of trusting stored metadata."""
    if not container_id:
        return False
    rc, out, _err = await _podman(
        "inspect", "--format", "{{.State.Running}}", container_id, timeout=10
    )
    return rc == 0 and out.strip().lower() == "true"


async def network_mode(container_id: str) -> str:
    """Return the live Podman network mode (for example ``none`` or ``bridge``)."""
    if not container_id:
        return ""
    rc, out, _err = await _podman(
        "inspect", "--format", "{{.HostConfig.NetworkMode}}", container_id, timeout=10
    )
    return out.strip().lower() if rc == 0 else ""


async def probe_agent_runtime(
    container_id: str,
    *,
    working_dir: str = "",
    require_write: bool = False,
    expected_network_policy: str = "",
) -> RuntimeReadiness:
    """Check the minimum command/file contract required by Agent builtin tools.

    Capability tags such as ``jdk17`` remain administrator-declared metadata.  This
    probe verifies the common transport contract and the configured workspace only.
    """
    if not await is_running(container_id):
        return RuntimeReadiness(False, "容器未运行或 daemon 不可达")
    if expected_network_policy == "engagement-scope":
        return RuntimeReadiness(False, "engagement-scope 仅允许使用受控 engagement 沙箱")
    live_network = ""
    network_access = "not_checked"
    if expected_network_policy in {"none", "internet"}:
        live_network = await network_mode(container_id)
        if expected_network_policy == "none" and live_network != "none":
            return RuntimeReadiness(
                False,
                "Profile 声明禁网，但容器实际网络模式不是 none",
                network_mode=live_network,
                network_access="unavailable",
            )
        if expected_network_policy == "internet" and live_network in {"", "none"}:
            return RuntimeReadiness(
                False,
                "Profile 声明联网，但容器实际没有可用网络",
                network_mode=live_network,
                network_access="unavailable",
            )
        if expected_network_policy == "none":
            network_access = "disabled"

    checks = ["command -v sh", "command -v cat", "command -v tee", "command -v grep", "command -v find"]
    if working_dir:
        quoted = shlex.quote(working_dir)
        checks.append(f"test -d {quoted}")
        if require_write:
            checks.append(f"test -w {quoted}")
    res = await exec(container_id, ["sh", "-c", " && ".join(checks)], timeout=20)
    if res.exit_code != 0:
        detail = (res.stderr or res.stdout or f"exit {res.exit_code}").strip()[:200]
        return RuntimeReadiness(
            False,
            f"Agent runtime 探针失败：{detail}",
            network_mode=live_network,
            network_access=network_access,
        )

    if expected_network_policy == "internet":
        egress = await probe_network_egress(container_id)
        if egress.exit_code != 0:
            detail = (egress.stderr or egress.stdout or f"exit {egress.exit_code}").strip()[:200]
            return RuntimeReadiness(
                False,
                f"容器 HTTPS 出网探针失败：{detail}",
                network_mode=live_network,
                network_access="unavailable",
            )
        network_access = "available"

    return RuntimeReadiness(
        True,
        "ready",
        network_mode=live_network,
        network_access=network_access,
    )


async def list_containers() -> list[ContainerSummary]:
    """列出所有容器（含已停）—— `podman ps -a`，解析 JSON。daemon 不可达则抛 RuntimeError。"""
    rc, out, err = await _podman("ps", "-a", "--format", "json", timeout=15)
    if rc != 0:
        raise RuntimeError(f"podman ps 失败：{err[:300]}")
    data = json.loads(out or "[]")
    result: list[ContainerSummary] = []
    for c in data:
        names = c.get("Names") or []
        result.append(ContainerSummary(
            id=c.get("Id", ""),
            name=names[0] if names else "",
            image=c.get("Image", ""),
            state=c.get("State", ""),
        ))
    return result


async def create_container(
    name: str,
    image: str,
    ports: list[str],
    env_vars: list[str],
    command: list[str] | None = None,
    *,
    network_mode: str = "bridge",
    working_dir: str = "",
) -> str:
    """`podman create`（不启动）：保留 TTY/stdin，配置端口、环境、网络和工作目录。

    容器是否常驻由镜像 CMD 或显式 command 决定；Agent runtime 应使用长期运行命令。
    返回 podman 容器 ID。同名冲突直接报错，绝不删除非本次请求创建的容器。
    """
    argv = ["create", "-t", "-i"]
    if name:
        argv += ["--name", name]
    for p in ports:
        argv += ["-p", p]
    for e in env_vars:
        argv += ["-e", e]
    if network_mode:
        argv += ["--network", network_mode]
    if working_dir:
        argv += ["--workdir", working_dir]
    argv.append(image)
    if command:
        argv += command

    rc, out, err = await _podman(*argv, timeout=120)
    if rc != 0:
        raise RuntimeError(f"podman create {name!r} 失败：{err[:300]}")
    return out.strip().splitlines()[-1] if out.strip() else ""


async def start(container_id: str) -> None:
    rc, _o, err = await _podman("start", container_id, timeout=_START_TIMEOUT)
    # 远端 Podman API 可能已接受启动、但 CLI 等待响应超时。以 daemon live state
    # 复核后再决定失败，避免实体已运行而数据库/GUI仍显示未启动。
    if rc == 124 and await is_running(container_id):
        log.warning(
            "podman.start.response_timeout_but_running",
            container_id=container_id[:16],
        )
        return
    if rc != 0:
        raise RuntimeError(f"podman start 失败：{err[:300]}")


async def stop(container_id: str) -> None:
    """停容器（10s 宽限，对齐 nexus）。"""
    rc, _o, err = await _podman("stop", "-t", "10", container_id, timeout=30)
    if rc != 0:
        raise RuntimeError(f"podman stop 失败：{err[:300]}")


async def remove(container_id: str) -> None:
    """强删容器（幂等，best-effort）。"""
    await _podman("rm", "-f", container_id, timeout=30)


async def exec(  # noqa: A001 — 沿用 nexus/docker SDK 语义命名；调用方以 podman.exec 显式限定
    container_id: str,
    command: list[str],
    *,
    working_dir: str = "",
    env: list[str] | None = None,
    timeout: float = 60,  # noqa: ASYNC109 — 透传给容器 exec 的执行超时
    stdin: str | None = None,
) -> ExecResult:
    """在运行中的容器里跑一条命令（`podman exec`）。stdout/stderr 由 OS 分流，无需 demux。"""
    argv = ["exec"]
    if stdin is not None:
        argv.append("-i")
    if working_dir:
        argv += ["-w", working_dir]
    for e in env or []:
        argv += ["-e", e]
    argv.append(container_id)
    argv += command
    rc, out, err = await _podman(*argv, stdin=stdin, timeout=timeout)
    return ExecResult(exit_code=rc, stdout=out, stderr=err)


async def exec_record(
    record_id: str,
    command: list[str],
    *,
    working_dir: str = "",
    env: list[str] | None = None,
    timeout: float = 60,  # noqa: ASYNC109 — 执行超时透传
    stdin: str | None = None,
) -> ExecResult:
    """按 ContainerRecord.id 解析出 podman 容器 id 再 exec —— 工具 is_container 路径用。

    exec_env.container_id 存的是 DB 记录 id（非 podman id，见 tools/exec_context.py），
    这里做 nexus 原先 `/containers/:id/exec` 里的「记录→podman id」查表（本地直连、免自调 HTTP）。
    """
    from harness.infra.db import ContainerRecord, session_factory

    async with session_factory()() as db:
        rec = await db.get(ContainerRecord, record_id)
    if rec is None or not rec.container_id:
        log.warning("podman.exec_record.no_container", record_id=record_id)
        return ExecResult(exit_code=127, stdout="", stderr=f"容器记录不存在或未创建：{record_id}")
    return await exec(
        rec.container_id, command, working_dir=working_dir, env=env, timeout=timeout, stdin=stdin
    )
