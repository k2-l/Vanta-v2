"""podman CLI 封装 —— 容器管理（原 nexus-svc services/podman.go 端口）。

harness 容器内自带 podman CLI + 挂宿主 podman socket（CONTAINER_HOST，见 dev-up.sh），
故直接 shell 出去调 `podman`，与 security/sandbox.py 同款（不引 docker/podman SDK 依赖）。
命令构造为纯参数、调用走 asyncio 子进程；异常统一转 RuntimeError 交由调用方兜底。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from harness.infra.logging import log


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
    name: str, image: str, ports: list[str], env_vars: list[str], command: list[str] | None = None
) -> str:
    """`podman create`（不启动）：`-t -i` 常驻以支持后续 exec（等价 docker run -dit），端口/env 映射。

    返回 podman 容器 ID。名字被占用（孤儿：库记录丢了但容器还在）→ 强删旧的重建，保持幂等
    （对齐 nexus podman.go：避免库/podman 不同步时调用方永远 500）。
    """
    argv = ["create", "-t", "-i"]
    if name:
        argv += ["--name", name]
    for p in ports:
        argv += ["-p", p]
    for e in env_vars:
        argv += ["-e", e]
    argv.append(image)
    if command:
        argv += command

    rc, out, err = await _podman(*argv, timeout=120)
    if rc != 0 and name and "already in use" in err.lower():
        await _podman("rm", "-f", name, timeout=30)
        rc, out, err = await _podman(*argv, timeout=120)
    if rc != 0:
        raise RuntimeError(f"podman create {name!r} 失败：{err[:300]}")
    return out.strip().splitlines()[-1] if out.strip() else ""


async def start(container_id: str) -> None:
    rc, _o, err = await _podman("start", container_id)
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
