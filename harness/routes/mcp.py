"""MCP server 可视化管理 — 读写都在 harness（连接状态是 harness 进程内运行时态，
不宜外部缓存）。

持久化：复用 harness/infra/config_store.py 的 config.json 覆盖层，把整个
mcp_servers 列表作为一个键整体 save（不直接写 data/config.toml，不进 routes/config.py
的 EDITABLE 白名单 —— 那条路径是"单字段 PATCH"，这里是"列表级整体替换"，语义不同）。

写门槛（新增/删除）：本期不复用 harness/infra/approvals.py 的 HITL 审批门——那套机制
是为 agent 工具调用流设计的同步阻塞原语，强绑定 session_id + 一个活跃的 WS 连接来转发
approval_required 事件 + 等待前端 resolve，REST 管理端点没有这个会话上下文，硬接会很别扭。
改用更轻量的显式确认：请求体须带 `confirm: true`，否则 422；前端二次确认弹窗展示将执行
的 command 全文后才把 confirm 置真（见 web/src/features/mcp/McpPage.tsx）。

env 脱敏：GET 一律不回明文 env，只回 env 的 key 名（env_keys），值本身只在内存/子进程
环境变量中存在。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from harness.app.auth import require_auth
from harness.infra import config_store
from harness.infra.logging import log
from harness.infra.settings import get_settings
from harness.tools.mcp import manager
from harness.tools.registry import registry

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


# ─── Pydantic ────────────────────────────────────────────────────────

class MCPServerSpec(BaseModel):
    """新增 MCP server 的请求体。confirm 是写门槛（见模块 docstring）。"""

    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    enabled: bool = True
    confirm: bool = Field(default=False, description="二次确认标志，必须显式为 true 才会执行")


class MCPToolView(BaseModel):
    name: str          # 本地注册名：mcp__<server>__<tool>
    remote_name: str   # 远端原名


class MCPServerView(BaseModel):
    """合并视图：持久配置（骨架）+ manager 运行时状态（status/error/tools）。"""

    name: str
    command: str
    args: list[str] = []
    enabled: bool = True
    env_keys: list[str] = []          # 脱敏：只回 key 名，不回明文 value
    status: str = "disconnected"      # connected | disconnected | error
    error: str | None = None
    tool_count: int = 0
    tools: list[MCPToolView] = []      # 列表接口省略（太大），详情接口才填充


# ─── 内部辅助 ────────────────────────────────────────────────────────

def _persisted_specs() -> list[dict[str, Any]]:
    """读当前持久配置（settings.mcp_servers，已叠加 config.json 覆盖层）。"""
    return [s for s in get_settings().mcp_servers if isinstance(s, dict)]


def _to_view(spec: dict[str, Any], *, with_tools: bool = False) -> MCPServerView:
    """以持久配置为骨架，叠加 manager 运行时状态，组合成一项合并视图。"""
    name = spec.get("name", "")
    runtime = manager.snapshot().get(name)
    tool_names: list[str] = runtime.get("tools", []) if runtime else []

    if runtime is None:
        status, error = "disconnected", None
    else:
        status, error = runtime.get("status", "disconnected"), runtime.get("error")

    tools: list[MCPToolView] = []
    if with_tools:
        for full_name in tool_names:
            remote = full_name.split("__", 2)[-1] if full_name.count("__") >= 2 else full_name
            tools.append(MCPToolView(name=full_name, remote_name=remote))

    return MCPServerView(
        name=name,
        command=spec.get("command", ""),
        args=list(spec.get("args") or []),
        enabled=bool(spec.get("enabled", True)),
        env_keys=sorted((spec.get("env") or {}).keys()),
        status=status,
        error=error,
        tool_count=len(tool_names),
        tools=tools,
    )


def _save_servers(specs: list[dict[str, Any]]) -> None:
    """整体 save mcp_servers 列表（config_store.save 内部已 get_settings.cache_clear()）。"""
    config_store.save(get_settings().data_dir, {"mcp_servers": specs})


def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise HTTPException(422, "写操作需显式确认：请求体须带 confirm: true")


# 内置工具不允许被 MCP 名称覆盖：mcp__ 命名空间本身就是约定的隔离前缀，
# 这里只需防 server name 包含 "__" 导致拼出的工具名与已有内置工具撞名。
def _check_name_collision(server_name: str) -> None:
    prefix = f"mcp__{server_name}__"
    existing = [n for n in registry.names() if n.startswith(prefix)]
    if existing:
        raise HTTPException(409, f"名称冲突：已有工具以 {prefix} 为前缀（{existing[:3]}…）")


# ─── 路由 ────────────────────────────────────────────────────────────

@router.get("/servers")
async def list_servers(_: dict = Depends(require_auth)) -> list[MCPServerView]:
    """以持久配置为骨架、叠加运行时状态，返回合并视图列表。"""
    return [_to_view(s) for s in _persisted_specs()]


@router.get("/servers/{name}")
async def get_server(name: str, _: dict = Depends(require_auth)) -> MCPServerView:
    spec = next((s for s in _persisted_specs() if s.get("name") == name), None)
    if spec is None:
        raise HTTPException(404, f"MCP server 不存在：{name}")
    return _to_view(spec, with_tools=True)


@router.post("/servers", status_code=201)
async def create_server(req: MCPServerSpec, _: dict = Depends(require_auth)) -> MCPServerView:
    """新增 MCP server：校验 → 持久化 → 热挂载，返回合并视图。"""
    _require_confirm(req.confirm)

    name = req.name.strip()
    if not name:
        raise HTTPException(400, "name 不能为空")
    if not req.command.strip():
        raise HTTPException(400, "command 不能为空")

    specs = _persisted_specs()
    if any(s.get("name") == name for s in specs):
        raise HTTPException(409, f"MCP server 已存在：{name}")
    _check_name_collision(name)

    spec = {
        "name": name,
        "command": req.command.strip(),
        "args": req.args,
        "env": req.env,
        "enabled": req.enabled,
    }
    specs.append(spec)
    _save_servers(specs)
    log.info("mcp.server_created", server=name)

    if req.enabled:
        await manager.mount(spec)
    return _to_view(spec, with_tools=True)


class DeleteConfirm(BaseModel):
    confirm: bool = Field(default=False, description="二次确认标志，必须显式为 true 才会执行")


@router.delete("/servers/{name}", status_code=200)
async def delete_server(
    name: str, body: DeleteConfirm, _: dict = Depends(require_auth)
) -> dict[str, Any]:
    """删除 MCP server：热卸载（drain 延迟关子进程）+ 从持久配置移除。"""
    _require_confirm(body.confirm)

    specs = _persisted_specs()
    remaining = [s for s in specs if s.get("name") != name]
    if len(remaining) == len(specs):
        raise HTTPException(404, f"MCP server 不存在：{name}")

    removed_tools = await manager.unmount(name, drain=True)
    _save_servers(remaining)
    log.info("mcp.server_deleted", server=name, removed_tools=len(removed_tools))
    return {"status": "ok", "name": name, "removed_tools": removed_tools}


@router.post("/servers/{name}/test")
async def test_server(name: str, _: dict = Depends(require_auth)) -> dict[str, Any]:
    """测试连接：用持久配置中的 spec 临时拉起一次，不入册不写库。"""
    spec = next((s for s in _persisted_specs() if s.get("name") == name), None)
    if spec is None:
        raise HTTPException(404, f"MCP server 不存在：{name}")
    return await manager.test(spec)
