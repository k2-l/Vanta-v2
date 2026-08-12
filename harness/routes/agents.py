"""Agent CRUD — 纯文件系统，Claude Code 格式。

数据源: {VANTA_ROOT}/workspace/agents/*/AGENT.md
无 DB 依赖。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from harness.app.auth import require_auth

router = APIRouter(prefix="/v1", tags=["agents"])

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


# ═══════════════════════════════════════════════════════════
# 文件系统辅助
# ═══════════════════════════════════════════════════════════


def _agents_root() -> Path:
    vanta_root = os.getenv("VANTA_ROOT", str(Path.home() / "Vanta"))
    d = Path(vanta_root) / "workspace" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _agent_dir(name: str) -> Path:
    return _agents_root() / name


def _agent_md_path(name: str) -> Path:
    return _agent_dir(name) / "AGENT.md"


def _parse_agent_md(raw: str) -> tuple[dict, str]:
    """解析 YAML front matter，返回 (meta, body)"""
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw

    import yaml

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}

    return meta, raw[match.end() :]


def _read_agent(name: str) -> tuple[dict, str] | None:
    """读取并解析 AGENT.md，返回 (meta, body)；不存在返回 None"""
    md_path = _agent_md_path(name)
    if not md_path.is_file():
        return None
    raw = md_path.read_text(encoding="utf-8")
    return _parse_agent_md(raw)


def _write_agent(name: str, meta: dict, body: str) -> None:
    """写入 AGENT.md"""
    agent_dir = _agent_dir(name)
    agent_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for key in ["name", "description", "model"]:
        if key in meta and meta[key]:
            lines.append(f"{key}: {meta[key]}")
    if "tools" in meta and meta["tools"]:
        lines.append("tools:")
        for t in meta["tools"]:
            lines.append(f"  - {t}")
    if "skills" in meta and meta["skills"]:
        lines.append("skills:")
        for s in meta["skills"]:
            lines.append(f"  - {s}")
    for key in ["max_tokens", "temperature"]:
        if key in meta and meta[key] is not None:
            lines.append(f"{key}: {meta[key]}")
    for key in ["allow_autonomous", "enable_critic"]:
        if key in meta:
            lines.append(f"{key}: {'true' if meta[key] else 'false'}")

    content = "---\n" + "\n".join(lines) + "\n---\n" + body
    _agent_md_path(name).write_text(content, encoding="utf-8")


def _delete_agent_dir(name: str) -> None:
    """删除整个 Agent 目录"""
    import shutil

    agent_dir = _agent_dir(name)
    if agent_dir.is_dir():
        shutil.rmtree(agent_dir)


def _list_agents() -> list[dict]:
    """扫描所有 Agent 目录，返回 L1 信息列表"""
    root = _agents_root()
    agents = []
    for agent_dir in sorted(root.iterdir()):
        if not agent_dir.is_dir():
            continue
        name = agent_dir.name
        parsed = _read_agent(name)
        if parsed is None:
            continue
        meta, _body = parsed
        agents.append(
            {
                "id": name,
                "name": name,
                "description": meta.get("description", ""),
                "model": meta.get("model", ""),
                "tools": meta.get("tools", []),
                "skills": meta.get("skills", []),
            }
        )
    return agents


def _invalidate_caches() -> None:
    """通知缓存失效"""
    try:
        from harness.core.context.builder import invalidate_context_cache

        invalidate_context_cache()
    except Exception:
        pass
    try:
        from harness.skills.loader import invalidate_entries_cache

        invalidate_entries_cache()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# Pydantic
# ═══════════════════════════════════════════════════════════


class RegisterAgentRequest(BaseModel):
    md: str


class AgentPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    allow_autonomous: bool | None = None
    enable_critic: bool | None = None


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════


@router.get("/agents")
async def list_agents(_: dict = Depends(require_auth)) -> list[dict]:
    return _list_agents()


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, _: dict = Depends(require_auth)) -> dict:
    parsed = _read_agent(agent_id)
    if parsed is None:
        raise HTTPException(404, "Agent 不存在")
    meta, body = parsed
    return {
        "id": agent_id,
        "name": meta.get("name", agent_id),
        "description": meta.get("description", ""),
        "content": body,
        "model": meta.get("model", ""),
        "tools": meta.get("tools", []),
        "skills": meta.get("skills", []),
        "max_tokens": meta.get("max_tokens", 8192),
        "temperature": meta.get("temperature", 0.5),
        "allow_autonomous": meta.get("allow_autonomous", False),
        "enable_critic": meta.get("enable_critic", False),
    }


@router.post("/agents/register", status_code=201)
async def register_agent(req: RegisterAgentRequest, _: dict = Depends(require_auth)) -> dict:
    meta, body = _parse_agent_md(req.md)
    name = (meta.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "frontmatter 缺少 name 字段")

    _write_agent(name, meta, body)
    _invalidate_caches()

    return {
        "id": name,
        "name": name,
        "description": meta.get("description", ""),
        "content": body,
        "model": meta.get("model", ""),
        "tools": meta.get("tools", []),
        "skills": meta.get("skills", []),
    }


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, patch: AgentPatch, _: dict = Depends(require_auth)) -> dict:
    parsed = _read_agent(agent_id)
    if parsed is None:
        raise HTTPException(404, "Agent 不存在")

    meta, body = parsed

    if patch.name is not None and patch.name != agent_id:
        _delete_agent_dir(agent_id)
        agent_id = patch.name

    if patch.description is not None:
        meta["description"] = patch.description
    if patch.content is not None:
        body = patch.content
    if patch.tools is not None:
        meta["tools"] = patch.tools
    if patch.skills is not None:
        meta["skills"] = patch.skills
    if patch.model is not None:
        meta["model"] = patch.model
    if patch.max_tokens is not None:
        meta["max_tokens"] = patch.max_tokens
    if patch.temperature is not None:
        meta["temperature"] = patch.temperature
    if patch.allow_autonomous is not None:
        meta["allow_autonomous"] = patch.allow_autonomous
    if patch.enable_critic is not None:
        meta["enable_critic"] = patch.enable_critic

    meta["name"] = agent_id  # frontmatter 名与目录名（=id=loader 索引键）对齐
    _write_agent(agent_id, meta, body)
    _invalidate_caches()

    return {
        "id": agent_id,
        "name": meta.get("name", agent_id),
        "description": meta.get("description", ""),
        "content": body,
        "model": meta.get("model", ""),
        "tools": meta.get("tools", []),
        "skills": meta.get("skills", []),
    }


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, _: dict = Depends(require_auth)) -> None:
    if not _agent_dir(agent_id).is_dir():
        raise HTTPException(404, "Agent 不存在")
    _delete_agent_dir(agent_id)
    _invalidate_caches()


@router.get("/agents/{agent_id}/deps")
async def agent_dep_tree(agent_id: str, _: dict = Depends(require_auth)) -> dict:
    """文件系统模式下无依赖树概念，返回空"""
    parsed = _read_agent(agent_id)
    if parsed is None:
        raise HTTPException(404, "Agent 不存在")
    return {"name": agent_id, "tree": ""}
