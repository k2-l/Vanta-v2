"""实体文件的 frontmatter 解析 + 序列化 + 实体目录扫描/写入（供 BaseFileProvider 复用）。

约定的文件布局（目录式，每实体一目录）：
    <root>/<name>/<filename>      例如 workspace/agents/audit/AGENT.md

解析：split_frontmatter —— 失败时元数据为空，绝不抛异常。
序列化：to_frontmatter —— 输出模型明确承载的字段（CC 标准字段 + Vanta critic 开关）。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

from harness.contracts.models import AgentFull, EntityFull, SkillFull

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


# ── frontmatter 解析 ────────────────────────────────────────


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """分离 YAML front matter 与正文；缺失或解析失败时元数据为空。"""
    match = _FM_RE.match(raw)
    if not match:
        return {}, raw
    try:
        import yaml

        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, raw[match.end() :]


def parse_bool(value: object, default: bool = False) -> bool:
    """容错解析布尔：bool / 数字 0·1 / 字符串 "true|false|yes|no|on|off"。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"true", "yes", "on", "1"}:
        return True
    if s in {"false", "no", "off", "0"}:
        return False
    return default


def normalize_str_list(value: object) -> list[str]:
    """容错归一为字符串列表：str → [str]，list → 逐项 str，其余 → []。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


# ── frontmatter 序列化（CC 标准字段，模型即契约） ────────────


def to_frontmatter(full: EntityFull) -> dict:
    """EntityFull → 受支持的 frontmatter dict。

    未进入模型契约的自定义字段不会被写出；Agent 额外支持 Vanta enable_critic。
    与 CC 惯例一致：disable-model-invocation 仅 true 时写出，user-invocable 仅 false 时写出。
    """
    fm: dict[str, object] = {
        "name": full.meta.name,
        "description": full.meta.description,
    }
    if full.meta.disable_model_invocation:
        fm["disable-model-invocation"] = True
    if not full.meta.user_invocable:
        fm["user-invocable"] = False
    if full.model:
        fm["model"] = full.model
    if full.provider:
        fm["provider"] = full.provider
    if isinstance(full, AgentFull):
        if full.tools:
            fm["tools"] = full.tools
        if full.enable_critic:
            fm["enable_critic"] = True
    if isinstance(full, SkillFull):
        if full.allowed_tools:
            fm["allowed-tools"] = full.allowed_tools
        if full.argument_hint:
            fm["argument-hint"] = full.argument_hint
    return fm


def dump_frontmatter(meta: dict) -> str:
    """把 frontmatter dict 序列化为 YAML 文本。"""
    if not meta:
        return ""
    import yaml

    # width 放大避免长 description 被折行；sort_keys=False 保持字段顺序
    return yaml.safe_dump(
        dict(meta), sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096
    ).rstrip("\n")


def render_md(full: EntityFull) -> str:
    """组装完整实体文件内容：CC frontmatter + 正文。"""
    fm = dump_frontmatter(to_frontmatter(full))
    return f"---\n{fm}\n---\n{full.content}" if fm else full.content


# ── 实体目录扫描 / 写入 ─────────────────────────────────────


def iter_entity_dirs(root: Path, filename: str) -> Iterator[tuple[str, Path, Path]]:
    """遍历 <root>/<dirname>/<filename>，产出 (dirname, dir_path, md_path)。"""
    if not root.is_dir():
        return
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        md = d / filename
        if md.is_file():
            yield d.name, d, md


def write_entity(root: Path, name: str, filename: str, full: EntityFull) -> Path:
    """把实体按 CC 标准格式写入 <root>/<name>/<filename>，返回文件路径。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / filename
    md.write_text(render_md(full), encoding="utf-8")
    return md


def delete_entity(root: Path, name: str) -> bool:
    """删除实体目录 <root>/<name>；不存在返回 False。"""
    d = root / name
    if not d.is_dir():
        return False
    shutil.rmtree(d)
    return True
