"""MCP（Model Context Protocol）stdio 客户端 — 把外部 MCP server 的工具接入工具集。

配置（data/config.toml，启动默认值；运行时增删见 harness/routes/mcp.py + config_store 覆盖层）：

    [[mcp.servers]]
    name    = "filesystem"
    command = "npx"
    args    = ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    # env   = { KEY = "VALUE" }   # 可选
    # enabled = true              # 可选，默认 true

启动时（FastAPI lifespan）调用 init_mcp_tools()：逐个拉起 stdio 子进程、initialize
握手、tools/list，并以 `mcp__<server>__<tool>` 注册进全局 registry；关闭时 shutdown_mcp()。
单个 server 失败只记 warning，不影响其余 server 与主服务启动。

热加载（P0/P1，见 harness/routes/mcp.py）：模块级 `manager`（MCPManager）支持运行时
mount/unmount 单个 server，无需重启进程。工具集变化后 registry 的 tools_hash() 自动变化，
agent 绑定模型的 cache key 随之失效，下一轮对话自动看见/看不见新增/删除的 MCP 工具。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from typing import Any

from harness.infra.logging import log
from harness.infra.settings import get_settings
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import registry

_PROTOCOL_VERSION = "2024-11-05"
_REQUEST_TIMEOUT = 30.0
_DRAIN_SECONDS = 5.0  # 热卸载延迟关子进程，给 in-flight 工具调用留窗口
_RECONNECT_COOLDOWN = 5.0  # 按需重连的冷却间隔：持续宕机时避免每次调用都 spawn 子进程


class MCPClient:
    """管理单个 MCP stdio server 的生命周期与 JSON-RPC 通信（请求经 lock 串行化）。"""

    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict | None = None) -> None:
        self.name = name
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._id = 0
        self._lock = asyncio.Lock()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._stderr_task: asyncio.Task | None = None
        self._restart_lock = asyncio.Lock()  # 串行化按需重连，防并发重启
        self._last_restart = 0.0  # 上次重连尝试的 monotonic 时刻（冷却用）

    async def start(self) -> None:
        full_env = {**os.environ, **{str(k): str(v) for k, v in self._env.items()}}
        self._proc = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "vanta-harness", "version": "0.1.0"},
        })
        await self._notify("notifications/initialized")

    async def _drain_stderr(self) -> None:
        """后台持续读 stderr 进有界缓冲，既避免 stderr 写满导致死锁，又保留尾部供报错。"""
        if self._proc is None or self._proc.stderr is None:
            return
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            self._stderr_tail.append(line.decode("utf-8", "replace").rstrip())

    async def list_tools(self) -> list[dict]:
        res = await self._request("tools/list", {})
        return res.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        try:
            return await self._request("tools/call", {"name": name, "arguments": arguments})
        except Exception:  # noqa: BLE001 — 宽接后用 _is_dead 把关，只对"连接已死"重连
            # 死连接的报错既可能是 RuntimeError（stdout 已关闭），也可能是写 stdin 时的
            # OSError（BrokenPipeError 等）；故宽接，再靠 _is_dead 区分：连接仍活（工具级
            # 错误 / 超时）照常抛出，只有子进程确实已退出才自愈重连。
            if not self._is_dead():
                raise
            await self._restart()  # 受冷却/串行守卫；冷却中或重启失败会抛出，降级为普通报错
            log.info("mcp.reconnect.retry", server=self.name, tool=name)
            return await self._request("tools/call", {"name": name, "arguments": arguments})

    def _is_dead(self) -> bool:
        """子进程不存在或已退出（returncode 落定）→ 连接已死。"""
        return self._proc is None or self._proc.returncode is not None

    async def _restart(self) -> None:
        """连接已死时就地重启子进程（重跑 start 的 spawn + initialize 握手）。

        _restart_lock 串行化防并发重启；_RECONNECT_COOLDOWN 冷却防持续宕机时每次
        调用都 spawn。持锁后复查 _is_dead：别的协程已重启好则直接返回。重启保持同一
        MCPClient 对象，故已注册的 MCPTool 持有的 client 引用仍有效，无需重注册工具。
        """
        async with self._restart_lock:
            if not self._is_dead():
                return
            now = time.monotonic()
            if now - self._last_restart < _RECONNECT_COOLDOWN:
                raise RuntimeError(
                    f"MCP '{self.name}' 重连冷却中（{_RECONNECT_COOLDOWN:.0f}s 内已尝试过）"
                )
            self._last_restart = now
            if self._stderr_task:
                self._stderr_task.cancel()
            self._proc = None
            await self.start()
            log.info("mcp.reconnected", server=self.name)

    async def _request(self, method: str, params: dict) -> dict:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError(f"MCP server '{self.name}' 未启动")
        async with self._lock:
            self._id += 1
            rid = self._id
            payload = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            self._proc.stdin.write(payload.encode() + b"\n")
            await self._proc.stdin.drain()
            while True:
                try:
                    line = await asyncio.wait_for(self._proc.stdout.readline(), _REQUEST_TIMEOUT)
                except TimeoutError as exc:
                    raise RuntimeError(f"MCP '{self.name}' {method} 超时（>{_REQUEST_TIMEOUT}s）") from exc
                if not line:
                    raise RuntimeError(f"MCP '{self.name}' stdout 已关闭；stderr: {' | '.join(self._stderr_tail)}")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 容忍 server 误写到 stdout 的非 JSON 行
                if msg.get("id") == rid:
                    if "error" in msg:
                        raise RuntimeError(f"MCP '{self.name}' {method} 错误：{msg['error']}")
                    return msg.get("result", {})
                # 其它 id / 通知：忽略，继续读

    async def _notify(self, method: str, params: dict | None = None) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._proc.stdin.write(json.dumps(msg).encode() + b"\n")
        await self._proc.stdin.drain()

    async def close(self) -> None:
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), 5)
            except (ProcessLookupError, TimeoutError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass


class MCPTool(Tool):
    """把一个远程 MCP 工具包装成本地 Tool，名为 mcp__<server>__<tool>。"""

    category = "mcp"
    # MCP 工具藏在 tool_search 之后按需披露，避免多 server 时 prompt 膨胀。
    disclosure = "dynamic"

    def __init__(self, client: MCPClient, remote_name: str, description: str, input_schema: dict | None) -> None:
        self._client = client
        self._remote_name = remote_name
        self.name = f"mcp__{client.name}__{remote_name}"
        self.description = description or f"MCP 工具 {remote_name}（来自 server {client.name}）"
        self.input_schema = input_schema or {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> ToolResult:
        try:
            res = await self._client.call_tool(self._remote_name, kwargs)
            parts: list[str] = []
            for c in res.get("content", []):
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
                else:
                    parts.append(json.dumps(c, ensure_ascii=False))
            out = "\n".join(parts)
            if res.get("isError"):
                return ToolResult(ok=False, output="", error=out or "MCP 工具返回 isError")
            return ToolResult(ok=True, output=out)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, output="", error=f"{type(exc).__name__}: {exc}")


class MCPManager:
    """按 name 管理所有 MCP server 的连接生命周期 + 运行时状态。

    与 ToolRegistry 的关系：mount 成功后逐个 registry.register(MCPTool(...))；
    unmount 时 registry.unregister_prefix(f"mcp__{name}__") 立即摘除工具（同步生效，
    下一轮 agent 对话即看不到），子进程关闭则按 drain 策略延迟，二者解耦。

    并发：所有写操作（mount/unmount）经 _lock 串行化，避免同名 server 并发
    增删时状态错乱；test() 不碰 manager 状态，无需加锁。
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._status: dict[str, dict[str, Any]] = {}  # name -> {status, error, tools}
        self._lock = asyncio.Lock()

    async def mount(self, spec: dict[str, Any]) -> dict[str, Any]:
        """拉起一个 MCP server 并注册其工具。幂等：已挂载同名 server 先原地卸载。

        单 server 失败只记 status="error"+stderr 尾、不向上抛异常（server 互相隔离，
        一个连不上不影响其余 server 与主服务）。返回该 server 的最新状态快照。
        """
        name = spec.get("name", "")
        command = spec.get("command", "")
        async with self._lock:
            if name in self._clients:
                await self._unmount_locked(name, drain=False)

            if not name or not command:
                self._status[name or "?"] = {"status": "error", "error": "缺少 name/command", "tools": []}
                return dict(self._status[name or "?"])

            client = MCPClient(name, command, spec.get("args") or [], spec.get("env") or {})
            try:
                await client.start()
                tools = await client.list_tools()
            except Exception as exc:  # noqa: BLE001
                stderr = " | ".join(client._stderr_tail)  # noqa: SLF001 — 同模块内部访问，报错诊断用
                err = str(exc)[:200] + (f"；stderr: {stderr}" if stderr else "")
                log.warning("mcp.server_failed", server=name, error=err)
                await client.close()
                self._status[name] = {"status": "error", "error": err, "tools": []}
                return dict(self._status[name])

            self._clients[name] = client
            tool_names: list[str] = []
            for t in tools:
                tool = MCPTool(client, t["name"], t.get("description", ""), t.get("inputSchema"))
                try:
                    registry.unregister(tool.name)  # 防残留（理论上 unmount 已清，双重保险）
                    registry.register(tool)
                    tool_names.append(tool.name)
                except (ValueError, KeyError) as exc:
                    log.warning("mcp.tool_skip", server=name, error=str(exc)[:120])
            self._status[name] = {"status": "connected", "error": None, "tools": tool_names}
            log.info("mcp.server_ready", server=name, tools=len(tool_names))
            return dict(self._status[name])

    async def unmount(self, name: str, *, drain: bool = True) -> list[str]:
        """卸载一个 MCP server：立即摘除其工具，子进程按 drain 策略延迟/立即关闭。

        返回被摘除的工具名列表（不存在时为空列表，幂等）。
        """
        async with self._lock:
            return await self._unmount_locked(name, drain=drain)

    async def _unmount_locked(self, name: str, *, drain: bool) -> list[str]:
        """unmount 的无锁版本，供已持锁的调用方（mount 的幂等重挂载）内部复用。"""
        removed = registry.unregister_prefix(f"mcp__{name}__")
        client = self._clients.pop(name, None)
        self._status.pop(name, None)
        if client is not None:
            if drain:
                asyncio.create_task(self._drain_close(name, client))
            else:
                await client.close()
        return removed

    async def _drain_close(self, name: str, client: MCPClient) -> None:
        """延迟关闭：给已摘除工具但仍 in-flight 的调用留出窗口期再杀子进程。"""
        await asyncio.sleep(_DRAIN_SECONDS)
        try:
            await client.close()
        except Exception as exc:  # noqa: BLE001 — drain 关闭失败不应影响主流程
            log.warning("mcp.drain_close_failed", server=name, error=str(exc)[:200])

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """返回所有已挂载 server 的运行时状态快照（name -> {status, error, tools}），供 GET 路由叠加到持久配置上。"""
        return {name: dict(s) for name, s in self._status.items()}

    async def test(self, spec: dict[str, Any]) -> dict[str, Any]:
        """临时拉起一个 MCP server 验证可连通性，用完即关，不进 registry/manager 状态。"""
        name = spec.get("name") or "_test_"
        command = spec.get("command", "")
        if not command:
            return {"ok": False, "error": "缺少 command", "tools": []}
        client = MCPClient(name, command, spec.get("args") or [], spec.get("env") or {})
        try:
            await client.start()
            tools = await client.list_tools()
            return {"ok": True, "error": None, "tools": [t.get("name", "") for t in tools]}
        except Exception as exc:  # noqa: BLE001
            stderr = " | ".join(client._stderr_tail)  # noqa: SLF001
            err = str(exc)[:200] + (f"；stderr: {stderr}" if stderr else "")
            return {"ok": False, "error": err, "tools": []}
        finally:
            await client.close()


manager = MCPManager()


async def init_mcp_tools() -> None:
    """启动配置中的 MCP servers 并注册其工具。单个 server 失败只 warning，不影响整体。"""
    for spec in get_settings().mcp_servers:
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        await manager.mount(spec)


async def shutdown_mcp() -> None:
    """进程关闭：逐个卸载，drain=False 直接关子进程（不需要留窗口期，进程本身都要退出了）。"""
    for name in list(manager._clients):  # noqa: SLF001 — 同模块内部访问
        await manager.unmount(name, drain=False)
