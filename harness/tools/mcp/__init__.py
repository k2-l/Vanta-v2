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
from harness.tools.source import SourceHealth, ToolSource, coordinator

_PROTOCOL_VERSION = "2024-11-05"
_REQUEST_TIMEOUT = 30.0
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


class MCPSource(ToolSource):
    """单个 MCP server 作为一个工具来源。id=mcp:<name>，kind=mcp。

    discover() 拉起 stdio 子进程 + tools/list，产出 MCPTool（不自注册，由协调器登记）；
    aclose() 关子进程。注册/摘除、drain 延迟、并发串行化统一由 ToolSourceCoordinator 负责。
    """

    kind = "mcp"

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        self.name = spec.get("name", "")
        self.id = f"mcp:{self.name}"
        self._client: MCPClient | None = None

    async def discover(self) -> list[Tool]:
        command = self._spec.get("command", "")
        if not self.name or not command:
            raise ValueError("缺少 name/command")
        client = MCPClient(self.name, command, self._spec.get("args") or [], self._spec.get("env") or {})
        try:
            await client.start()
            raw = await client.list_tools()
        except Exception as exc:  # noqa: BLE001 —— 把 stderr 尾附到异常，交协调器记 status
            stderr = " | ".join(client._stderr_tail)  # noqa: SLF001
            await client.close()
            raise RuntimeError(str(exc)[:200] + (f"；stderr: {stderr}" if stderr else "")) from exc
        self._client = client
        return [MCPTool(client, t["name"], t.get("description", ""), t.get("inputSchema")) for t in raw]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def health(self) -> SourceHealth:
        if self._client is None or self._client._is_dead():  # noqa: SLF001
            return SourceHealth(ok=False, detail="disconnected")
        return SourceHealth(ok=True)


class _MCPManagerFacade:
    """兼容门面：保留 routes/mcp.py 依赖的 mount/unmount/snapshot/test 旧签名，
    内部委托给统一的 ToolSourceCoordinator。server name ↔ source id(mcp:<name>) 转换在此。
    """

    async def mount(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self._strip(await coordinator.mount(MCPSource(spec)))

    async def unmount(self, name: str, *, drain: bool = True) -> list[str]:
        return await coordinator.unmount(f"mcp:{name}", drain=drain)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        # 协调器按 source id(mcp:<name>) 存；剥前缀回 server name，保持旧契约。
        return {
            sid[len("mcp:"):]: self._strip(st)
            for sid, st in coordinator.snapshot(kind="mcp").items()
        }

    @staticmethod
    def _strip(st: dict[str, Any]) -> dict[str, Any]:
        """去掉协调器内部的 kind 键，只回 routes 期望的 {status,error,tools}。"""
        return {
            "status": st.get("status", "disconnected"),
            "error": st.get("error"),
            "tools": st.get("tools", []),
        }

    async def test(self, spec: dict[str, Any]) -> dict[str, Any]:
        """临时拉起一个 MCP server 验证可连通性，用完即关，不进 registry/协调器状态。"""
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


manager = _MCPManagerFacade()


async def init_mcp_tools() -> None:
    """启动配置中的 MCP servers 并注册其工具。单个 server 失败只 warning，不影响整体。"""
    for spec in get_settings().mcp_servers:
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        await manager.mount(spec)


async def shutdown_mcp() -> None:
    """进程关闭：逐个卸载 MCP 来源，drain=False 直接关子进程（进程本身都要退出了）。"""
    for sid in list(coordinator.snapshot(kind="mcp")):
        await coordinator.unmount(sid, drain=False)
