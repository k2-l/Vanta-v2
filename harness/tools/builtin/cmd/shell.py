"""Bash 工具：经 shell 执行任意命令 + 超时 + 输出截断。

安全模型（ADR-0003 P3/T3.3）：不再用命令白名单沙箱，改由 execute_tool_core 的权限引擎
（harness/infra/permissions）在执行前按 allow/ask/deny 规则门控。本工具只负责"安全地把
命令交给 shell 跑并包装结果"。host 上限定在 workspace 工作目录内执行。

"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from harness.infra import podman
from harness.infra.settings import get_settings
from harness.security.permissions import _HOST_DENIED_TOOLS, _first_program
from harness.tools.base import Tool, ToolResult
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register

DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_BYTES = 32_768


def _decode_bytes(b: bytes) -> str:
    """先 UTF-8，再尝试系统中文编码，最后兜底替换。"""
    if not b:
        return ""
    candidates = ["utf-8"]
    if sys.platform == "win32":
        candidates.extend(["gbk", "cp936"])
    for enc in candidates:
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _command_result(
    returncode: int,
    stdout: str,
    stderr: str,
    *,
    artifacts: list[dict[str, Any]],
    truncate: bool = False,
) -> ToolResult:
    """把命令输出转换为统一结果；调用方决定是否按合并后长度截断。"""
    output = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
    if truncate:
        output = output[:MAX_OUTPUT_BYTES]
    return ToolResult(
        ok=returncode == 0,
        output=output,
        error=None if returncode == 0 else f"exit code {returncode}",
        artifacts=artifacts,
    )


def _resolve_cwd(cwd: str | None) -> tuple[str, str | None]:
    """校验并返回沙箱化的工作目录。返回 (resolved_path, error_str)。"""
    s = get_settings()
    workspace_dir = s.workspace_dir
    if not workspace_dir:
        return "", "安全策略：未配置工作目录"
    ws = Path(workspace_dir).resolve()
    if not ws.is_dir():
        return "", f"工作目录不存在：{ws}"
    if not cwd:
        return str(ws), None
    try:
        requested = Path(cwd).expanduser()
        target = (requested if requested.is_absolute() else ws / requested).resolve()
        target.relative_to(ws)
    except ValueError:
        return "", f"安全策略：工作目录超出范围：{cwd}"
    except OSError:
        return "", f"路径无效：{cwd}"
    if not target.exists():
        return "", f"目录不存在：{cwd}"
    if not target.is_dir():
        return "", f"不是目录：{cwd}"
    return str(target), None


async def _exec_command(command: str, cwd: str | None, timeout: float) -> ToolResult:  # noqa: ASYNC109 — 工具暴露的超时参数
    """经 shell 执行命令（host: sh -c；容器: podman.exec_record；engagement 扫描器: 沙箱）。"""
    exec_env = get_exec_env()
    # engagement 活跃 + 扫描器命令 → 路由进该 engagement 的 egress 锁定沙箱
    if exec_env.has_engagement and _first_program(command) in _HOST_DENIED_TOOLS:
        return await _run_in_sandbox(exec_env, command, timeout)
    if exec_env.is_container:
        res = await podman.exec_record(
            exec_env.container_id,
            ["sh", "-c", command],
            working_dir=cwd or "",
            timeout=int(timeout),
        )
        return _command_result(
            res.exit_code,
            res.stdout,
            res.stderr,
            artifacts=[{"returncode": res.exit_code}],
            truncate=True,
        )

    effective_cwd, cwd_error = _resolve_cwd(cwd)
    if cwd_error:
        code = "PERMISSION_DENIED" if cwd_error.startswith("安全策略") else "COMMAND_NOT_FOUND"
        return ToolResult.fail(error=cwd_error, error_code=code)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=effective_cwd,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(ok=False, output="", error=f"超时（>{timeout}s）")

    stdout = _decode_bytes(stdout_b[:MAX_OUTPUT_BYTES])
    stderr = _decode_bytes(stderr_b[:MAX_OUTPUT_BYTES])
    return _command_result(
        proc.returncode,
        stdout,
        stderr,
        artifacts=[{"returncode": proc.returncode}],
    )


async def _run_in_sandbox(exec_env, command: str, timeout: float) -> ToolResult:  # noqa: ASYNC109
    """把扫描器命令送进该 engagement 的 egress 锁定沙箱执行；起不来则优雅报错，绝不在沙箱外裸跑。"""
    from harness.security import sandbox as sbx

    try:
        manager = await sbx.get_or_create_sandbox(
            exec_env.engagement_id, exec_env.scope_targets, exec_env.dns_resolver_ip
        )
        rc, out, err = await manager.run_tool(["sh", "-c", command], timeout=int(timeout))
        return _command_result(
            rc,
            out,
            err,
            artifacts=[{"returncode": rc, "sandbox": exec_env.engagement_id}],
            truncate=True,
        )
    except Exception as exc:  # noqa: BLE001 —— 沙箱起不来=不在沙箱外裸跑，优雅报错
        return ToolResult.fail(
            error=(
                f"沙箱执行失败（{type(exc).__name__}: {str(exc)[:200]}）——"
                "扫描器须在 egress 锁定沙箱内跑，需 harness 具备 podman 通路。"
            ),
            error_code="SANDBOX_ERROR",
        )


@register
class ShellExecTool(Tool):
    name = "Bash"
    category = "exec"
    description = (
        "经 shell 执行命令并返回输出（支持管道、重定向、变量展开、复合命令）。"
        "命令的放行 / 审批 / 拒绝由权限策略统一管控；host 上在工作目录内执行。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "完整命令字符串，例如 'ls -la' 或 'grep -rn TODO src/ | head'",
            },
            "cwd": {
                "type": "string",
                "description": "工作目录，默认工作目录根",
            },
            "timeout": {
                "type": "number",
                "description": f"超时秒数，默认 {DEFAULT_TIMEOUT}",
                "default": DEFAULT_TIMEOUT,
            },
        },
        "required": ["command"],
    }

    async def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109 — 工具暴露的超时参数
    ) -> ToolResult:
        try:
            if not command.strip():
                return ToolResult(ok=False, output="", error="空命令")
            return await _exec_command(command, cwd, timeout)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")
