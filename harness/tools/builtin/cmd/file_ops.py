"""Read / Write 工具：受限路径下的文件读写。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness.infra import podman
from harness.infra.settings import get_settings
from harness.tools.base import Tool, ToolResult
from harness.tools.exec_context import get_exec_env
from harness.tools.registry import register

_FORBIDDEN_NAMES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.production",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "authorized_keys", "known_hosts",
    ".ssh", ".gnupg", ".aws",
})


def _sandbox_path(path: str) -> tuple[Path | None, str | None]:
    """规范化并校验路径在 workspace 内。返回 (resolved_path, error_str)。"""
    s = get_settings()
    workspace_root = s.workspace_dir
    if not workspace_root:
        return None, "安全策略：未配置工作目录"

    workspace = Path(workspace_root).resolve()
    try:
        requested = Path(path).expanduser()
        target = (requested if requested.is_absolute() else workspace / requested).resolve(strict=False)
    except (OSError, ValueError, RuntimeError):
        return None, "路径无效"

    if target.name in _FORBIDDEN_NAMES:
        return None, "安全策略禁止读取该文件"

    real = Path(os.path.realpath(str(target)))

    try:
        real.relative_to(workspace)
    except ValueError:
        return None, "安全策略：文件路径超出工作目录范围"

    return target, None


@register
class FileReadTool(Tool):
    name = "Read"
    category = "file"
    description = "读取工作目录下的文本文件，返回内容（最多 200KB）。仅支持文本文件。"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径，相对于当前工作目录或绝对路径",
            },
            "max_bytes": {
                "type": "integer",
                "description": "最多读取字节数，默认 200000",
                "default": 200000,
            },
        },
        "required": ["path"],
    }

    async def run(self, path: str, max_bytes: int = 200_000) -> ToolResult:
        try:
            exec_env = get_exec_env()
            if exec_env.is_container:
                res = await podman.exec_record(exec_env.container_id, ["cat", path], timeout=30)
                if res.exit_code != 0:
                    return ToolResult(ok=False, output="", error=res.stderr or f"exit code {res.exit_code}")
                text = res.stdout
                if len(text) > max_bytes:
                    text = text[:max_bytes] + f"\n\n[... 已截断，原文件 ≥ {max_bytes} 字节 ...]"
                return ToolResult(ok=True, output=text)

            p, err = _sandbox_path(path)
            if err:
                return ToolResult.fail(error=err, error_code="PERMISSION_DENIED")
            if not p.exists():
                return ToolResult(ok=False, output="", error=f"文件不存在：{p}")
            if not p.is_file():
                return ToolResult(ok=False, output="", error=f"不是文件：{p}")

            data = p.read_bytes()[: max_bytes + 1]
            truncated = len(data) > max_bytes
            text = data[:max_bytes].decode("utf-8", errors="replace")
            if truncated:
                text += f"\n\n[... 已截断，原文件 ≥ {max_bytes} 字节 ...]"
            return ToolResult(ok=True, output=text)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")


@register
class WriteFileTool(Tool):
    name = "Write"
    category = "file"
    description = "写入或追加文本到工作目录下的文件。路径必须在配置的工作目录范围内。"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目标文件路径（相对或绝对）",
            },
            "content": {
                "type": "string",
                "description": "要写入的文本内容",
            },
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "写入模式：overwrite 覆盖（默认）/ append 追加",
                "default": "overwrite",
            },
        },
        "required": ["path", "content"],
    }

    async def run(self, path: str, content: str, mode: str = "overwrite") -> ToolResult:
        try:
            exec_env = get_exec_env()
            if exec_env.is_container:
                cmd = ["tee", "-a", path] if mode == "append" else ["tee", path]
                res = await podman.exec_record(exec_env.container_id, cmd, stdin=content, timeout=30)
                if res.exit_code != 0:
                    return ToolResult(ok=False, output="", error=res.stderr or f"exit code {res.exit_code}")
                return ToolResult(ok=True, output=f"已写入：{path}")

            p, err = _sandbox_path(path)
            if err:
                return ToolResult.fail(error=err, error_code="PERMISSION_DENIED")

            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a" if mode == "append" else "w", encoding="utf-8") as f:
                f.write(content)
            verb = "追加" if mode == "append" else "写入"
            return ToolResult(ok=True, output=f"已{verb}：{p}（{len(content)} 字节）")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")


def _apply_edit(content: str, old: str, new: str, replace_all: bool) -> tuple[str | None, str | None]:
    """对文本做精确替换。返回 (new_content, error)；二者互斥。"""
    count = content.count(old)
    if count == 0:
        return None, "未找到 old_string（需与文件内容精确匹配，含缩进/空白）"
    if count > 1 and not replace_all:
        return None, f"old_string 不唯一（出现 {count} 次）；请补充上下文使其唯一，或设 replace_all=true"
    return (content.replace(old, new) if replace_all else content.replace(old, new, 1)), None


@register
class FileEditTool(Tool):
    name = "Edit"
    category = "file"
    description = (
        "对工作目录下的文本文件做精确字符串替换（old_string → new_string）。"
        "默认要求 old_string 在文件中唯一，未找到或不唯一会报错；replace_all=true 时替换全部匹配。"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对或绝对）"},
            "old_string": {"type": "string", "description": "要替换的原文，需与文件内容精确匹配（含缩进/空白）"},
            "new_string": {"type": "string", "description": "替换后的新文本"},
            "replace_all": {"type": "boolean", "description": "替换所有匹配（默认仅替换唯一一处）", "default": False},
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def run(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> ToolResult:
        try:
            if old_string == new_string:
                return ToolResult.fail(error="old_string 与 new_string 相同，无需编辑", error_code="INVALID_ARGS")
            exec_env = get_exec_env()
            if exec_env.is_container:
                read = await podman.exec_record(exec_env.container_id, ["cat", path], timeout=30)
                if read.exit_code != 0:
                    return ToolResult(ok=False, output="", error=read.stderr or f"读取失败：{path}")
                new_content, err = _apply_edit(read.stdout, old_string, new_string, replace_all)
                if err:
                    return ToolResult.fail(error=err, error_code="EDIT_FAILED")
                write = await podman.exec_record(exec_env.container_id, ["tee", path], stdin=new_content, timeout=30)
                if write.exit_code != 0:
                    return ToolResult(ok=False, output="", error=write.stderr or "写回失败")
                return ToolResult(ok=True, output=f"已编辑：{path}")

            p, err = _sandbox_path(path)
            if err:
                return ToolResult.fail(error=err, error_code="PERMISSION_DENIED")
            if not p.is_file():
                return ToolResult(ok=False, output="", error=f"文件不存在或不是文件：{p}")
            new_content, err = _apply_edit(p.read_text(encoding="utf-8"), old_string, new_string, replace_all)
            if err:
                return ToolResult.fail(error=err, error_code="EDIT_FAILED")
            p.write_text(new_content, encoding="utf-8")
            return ToolResult(ok=True, output=f"已编辑：{p}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")
