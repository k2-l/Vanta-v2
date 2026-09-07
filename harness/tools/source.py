"""工具来源统一协议 —— builtin / mcp / plugin 三类来源走同一条挂载路径。

设计要点：
  - 执行层早已统一（一切皆 Tool，落在同一个 registry；见 tools/base.py + registry.py）。
    本模块统一的是**来源接入的生命周期**：发现 → 注册 → 卸载/重载。
  - ToolSource 只管"产出什么工具"(discover) 和"如何释放后端资源"(aclose)；
    ToolSourceCoordinator 是唯一为 mount/unmount 改动全局 registry 的地方。
  - 加一个新来源 = 实现 ToolSource.discover() 一个方法。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from harness.infra.logging import log
from harness.tools.base import Tool
from harness.tools.registry import registry

_DRAIN_SECONDS = 5.0  # 卸载后延迟关后端资源，给 in-flight 调用留窗口（同 MCP 旧行为）


@dataclass
class SourceHealth:
    """来源存活探针结果。"""

    ok: bool
    detail: str = ""


class ToolSource(ABC):
    """一个工具来源：产出 Tool 实例，并（可选）持有其后端资源（子进程/连接等）。"""

    id: str  # 唯一来源 id，如 "builtin" / "mcp:kali" / "plugin:foo"
    kind: str  # builtin | mcp | plugin

    # True：工具已在 discover 之外自行注册进 registry（builtin 用 @register 装饰器在
    # import 时注册）；协调器只登记归属、不重复注册、也不在卸载时摘除（编译期常驻）。
    self_registers: bool = False

    @abstractmethod
    async def discover(self) -> list[Tool]:
        """产出本来源的工具实例（并按需启动后端资源）。"""

    async def aclose(self) -> None:  # noqa: B027 —— 可选钩子，无状态来源默认无操作
        """释放后端资源（子进程/连接）。默认无操作，无状态来源无需覆盖。"""

    async def health(self) -> SourceHealth:
        """存活探针。默认恒 ok，有连接的来源可覆盖。"""
        return SourceHealth(ok=True)


class ToolSourceCoordinator:
    """统一挂载所有工具来源：谁的工具归谁，卸载/重载只动那一撮。

    唯一为 mount/unmount 变更全局 registry 的地方（builtin 的 @register 装饰器是
    编译期例外，见 ToolSource.self_registers）。所有写操作经 _lock 串行化。
    """

    def __init__(self) -> None:
        self._sources: dict[str, ToolSource] = {}
        self._owned: dict[str, set[str]] = {}  # source_id -> 工具名集合
        self._status: dict[str, dict[str, Any]] = {}  # source_id -> {status,error,tools,kind}
        self._lock = asyncio.Lock()

    async def mount(self, source: ToolSource) -> dict[str, Any]:
        """发现并注册一个来源的工具。幂等：已挂载同 id 先原地卸载。

        discover 失败只记 status=error、不抛（来源互相隔离，一个失败不影响其余）。
        """
        async with self._lock:
            if source.id in self._sources:
                await self._unmount_locked(source.id, drain=False)
            try:
                tools = await source.discover()
            except Exception as exc:  # noqa: BLE001 —— 来源隔离，失败降级为 status
                self._status[source.id] = {
                    "status": "error",
                    "error": str(exc)[:200],
                    "tools": [],
                    "kind": source.kind,
                }
                log.warning("toolsource.discover_failed", source=source.id, error=str(exc)[:200])
                return dict(self._status[source.id])

            names: list[str] = []
            for t in tools:
                if source.self_registers:  # 已自注册，仅登记归属
                    names.append(t.name)
                    continue
                try:
                    if t.name in registry:
                        registry.unregister(t.name)  # 幂等替换（重挂载取最新实例）
                    registry.register(t)
                    names.append(t.name)
                except (ValueError, KeyError) as exc:
                    log.warning(
                        "toolsource.tool_skip", source=source.id, tool=t.name, error=str(exc)[:120]
                    )

            self._sources[source.id] = source
            self._owned[source.id] = set(names)
            self._status[source.id] = {
                "status": "connected",
                "error": None,
                "tools": names,
                "kind": source.kind,
            }
            log.info("toolsource.mounted", source=source.id, kind=source.kind, tools=len(names))
            return dict(self._status[source.id])

    async def unmount(self, source_id: str, *, drain: bool = True) -> list[str]:
        """卸载一个来源：立即摘除其工具，后端资源按 drain 策略延迟/立即释放。幂等。"""
        async with self._lock:
            return await self._unmount_locked(source_id, drain=drain)

    async def _unmount_locked(self, source_id: str, *, drain: bool) -> list[str]:
        names = sorted(self._owned.pop(source_id, set()))
        source = self._sources.pop(source_id, None)
        self._status.pop(source_id, None)
        # self_registers 来源（builtin）不由协调器注册，也不摘除（编译进程序，静态常驻）。
        if source is not None and not source.self_registers:
            for n in names:
                registry.unregister(n)
        if source is not None:
            if drain:
                asyncio.create_task(self._drain_close(source_id, source))
            else:
                await source.aclose()
        return names

    async def _drain_close(self, source_id: str, source: ToolSource) -> None:
        await asyncio.sleep(_DRAIN_SECONDS)
        try:
            await source.aclose()
        except Exception as exc:  # noqa: BLE001 —— drain 关闭失败不影响主流程
            log.warning("toolsource.drain_close_failed", source=source_id, error=str(exc)[:200])

    async def reload(self, source_id: str) -> dict[str, Any]:
        """重载一个已挂载来源（卸载后用同一 source 重新 discover）。"""
        source = self._sources.get(source_id)
        if source is None:
            return {"status": "error", "error": f"未挂载来源：{source_id}", "tools": [], "kind": ""}
        await self.unmount(source_id, drain=False)
        return await self.mount(source)

    def snapshot(self, *, kind: str | None = None) -> dict[str, dict[str, Any]]:
        """所有来源的运行时状态快照（source_id -> {status,error,tools,kind}），可按 kind 过滤。"""
        return {
            sid: dict(st)
            for sid, st in self._status.items()
            if kind is None or st.get("kind") == kind
        }

    def owned(self, source_id: str) -> set[str]:
        """某来源当前拥有的工具名集合（供归属查询）。"""
        return set(self._owned.get(source_id, set()))


coordinator = ToolSourceCoordinator()
