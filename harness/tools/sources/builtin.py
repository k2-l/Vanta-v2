"""BuiltinSource —— 把编译进程序的内置工具表达成一个 ToolSource。

内置工具用 @register 装饰器在 import 时自注册（见 registry.load_builtin_tools），
故 self_registers=True：协调器只登记归属、不重复注册，也不在卸载时摘除（静态常驻）。
存在的意义是让 builtin 与 mcp/plugin 在统一快照/归属里平齐。
"""

from __future__ import annotations

from harness.tools.base import Tool
from harness.tools.source import ToolSource


class BuiltinSource(ToolSource):
    id = "builtin"
    kind = "builtin"
    self_registers = True  # @register 装饰器 import 时已注册

    async def discover(self) -> list[Tool]:
        from harness.tools.registry import load_builtin_tools, registry

        load_builtin_tools()  # 触发 import 副作用 + 别名（幂等：模块已缓存则不重注册）
        return list(registry.list())  # 首个挂载，registry 内即全部 builtin
