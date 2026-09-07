"""PluginSource —— 从插件目录动态接入工具（新的可插拔接入点）。

插件契约：<plugins_dir>/<name>/ 是一个 Python 包，其 __init__.py 暴露
    def get_tools() -> list[Tool]: ...
协调器负责注册/卸载这些 Tool；插件不必自注册。目录不存在或为空 → 无插件，不报错
（插件是可选特性，settings.plugins_enabled 默认 False）。

新增一个插件 = 放一个包 + 写 get_tools()，无需改动 harness 任何代码。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from harness.infra.logging import log
from harness.infra.settings import get_settings
from harness.tools.base import Tool
from harness.tools.source import ToolSource, coordinator


class PluginSource(ToolSource):
    kind = "plugin"

    def __init__(self, pkg_dir: Path) -> None:
        self.name = pkg_dir.name
        self.id = f"plugin:{self.name}"
        self._dir = pkg_dir

    async def discover(self) -> list[Tool]:
        init = self._dir / "__init__.py"
        if not init.exists():
            raise FileNotFoundError(f"插件 {self.name} 缺少 __init__.py")
        spec = importlib.util.spec_from_file_location(f"vanta_plugin_{self.name}", init)
        if spec is None or spec.loader is None:
            raise ImportError(f"插件 {self.name} 无法加载")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        factory = getattr(mod, "get_tools", None)
        if not callable(factory):
            raise AttributeError(f"插件 {self.name} 未暴露 get_tools()")
        tools = factory()
        return [t for t in tools if isinstance(t, Tool)]


def discover_plugin_sources() -> list[PluginSource]:
    """扫描 settings.plugins_dir 下的子目录包，返回每个插件一个 PluginSource。"""
    root = Path(get_settings().plugins_dir)
    if not root.is_dir():
        return []
    return [
        PluginSource(p)
        for p in sorted(root.iterdir())
        if p.is_dir() and (p / "__init__.py").exists()
    ]


async def load_plugins() -> None:
    """挂载所有插件（settings.plugins_enabled=False 时直接跳过）。供启动时调用。"""
    if not get_settings().plugins_enabled:
        return
    for src in discover_plugin_sources():
        st = await coordinator.mount(src)
        log.info(
            "plugin.mounted",
            plugin=src.name,
            status=st.get("status"),
            tools=len(st.get("tools", [])),
        )
