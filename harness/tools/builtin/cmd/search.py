"""Grep / Glob 工具：工作目录（或当前容器）内的内容检索与文件名匹配。

与 Read/Write 一致的 dual-path：host 直接执行 grep/find（argv 直传、不经 shell，
无注入风险，且限定在 workspace 内）；容器内经 podman.exec 执行同样的命令。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from harness.infra import podman
from harness.infra.settings import get_settings
from harness.tools.base import Tool, ToolResult
from harness.tools.builtin.cmd.file_ops import _sandbox_path
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register


async def _run_host(argv: list[str], cwd: Path) -> tuple[str, str, int]:
    """在 cwd 下执行固定命令（argv 直传，不经 shell）。返回 (stdout, stderr, exit_code)。"""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 30)
    except TimeoutError:
        proc.kill()
        return "", "超时（>30s）", 124
    return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode or 0


@register
class GrepTool(Tool):
    name = "Grep"
    category = "file"
    description = (
        "按正则在工作目录（或当前容器）下搜索文件内容，返回匹配行（file:line:内容）。"
        "可用 include 限定文件名通配（如 *.py），path 限定子目录。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式（grep ERE）"},
            "path": {"type": "string", "description": "搜索根目录（相对/绝对），默认工作目录", "default": ""},
            "include": {"type": "string", "description": "文件名通配过滤，如 *.py（可选）", "default": ""},
            "max_results": {"type": "integer", "description": "最多返回匹配行数，默认 200", "default": 200},
        },
        "required": ["pattern"],
    }

    async def run(self, pattern: str, path: str = "", include: str = "", max_results: int = 200) -> ToolResult:
        try:
            argv = ["grep", "-rnIE"]
            if include:
                argv.append(f"--include={include}")
            argv += ["--", pattern]
            exec_env = get_exec_env()
            if exec_env.is_container:
                res = await podman.exec_record(exec_env.container_id, argv + [path or "."], timeout=30)
                out, err, code = res.stdout, res.stderr, res.exit_code
            else:
                base, perr = _sandbox_path(path or get_settings().workspace_dir)
                if perr:
                    return ToolResult.fail(error=perr, error_code="PERMISSION_DENIED")
                out, err, code = await _run_host(argv + ["."], cwd=base)
            if code not in (0, 1):  # grep: 0=有匹配 1=无匹配 ≥2=错误
                return ToolResult(ok=False, output="", error=err or f"grep exit {code}")
            lines = out.splitlines()
            if not lines:
                return ToolResult(ok=True, output="（无匹配）")
            body = "\n".join(lines[:max_results])
            if len(lines) > max_results:
                body += f"\n[... 已截断，共 {len(lines)} 行匹配 ...]"
            return ToolResult(ok=True, output=body)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")


@register
class GlobTool(Tool):
    name = "Glob"
    category = "file"
    description = (
        "在工作目录（或当前容器）下按文件名模式递归查找文件，返回相对路径列表。"
        "模式按文件名匹配（如 *.py 匹配所有 .py 文件）。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "文件名通配，如 *.py、*config*"},
            "path": {"type": "string", "description": "查找根目录（相对/绝对），默认工作目录", "default": ""},
            "max_results": {"type": "integer", "description": "最多返回路径数，默认 200", "default": 200},
        },
        "required": ["pattern"],
    }

    async def run(self, pattern: str, path: str = "", max_results: int = 200) -> ToolResult:
        try:
            exec_env = get_exec_env()
            if exec_env.is_container:
                argv = ["find", path or ".", "-name", pattern, "-type", "f"]
                res = await podman.exec_record(exec_env.container_id, argv, timeout=30)
                out, err, code = res.stdout, res.stderr, res.exit_code
            else:
                base, perr = _sandbox_path(path or get_settings().workspace_dir)
                if perr:
                    return ToolResult.fail(error=perr, error_code="PERMISSION_DENIED")
                out, err, code = await _run_host(["find", ".", "-name", pattern, "-type", "f"], cwd=base)
            if code != 0 and not out:
                return ToolResult(ok=False, output="", error=err or f"find exit {code}")
            paths = sorted(line for line in out.splitlines() if line.strip())
            if not paths:
                return ToolResult(ok=True, output="（无匹配文件）")
            body = "\n".join(paths[:max_results])
            if len(paths) > max_results:
                body += f"\n[... 已截断，共 {len(paths)} 个文件 ...]"
            return ToolResult(ok=True, output=body)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")
