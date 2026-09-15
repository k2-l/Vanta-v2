"""ToolRegistry — 集中注册和检索工具。

使用方式：
    from harness.tools.registry import register, registry

    @register
    class MyTool(Tool):
        name = "my_tool"
        ...
"""

from __future__ import annotations

from typing import TypeVar

from harness.tools.base import Tool

T = TypeVar("T", bound=Tool)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lc_tools_static_cache: list | None = None  # disclosure=="static" 子集缓存
        self._tools_hash_cache: int | None = None

    def _invalidate_caches(self) -> None:
        """工具集变动时统一清空派生缓存（static 子集 / hash）。"""
        self._lc_tools_static_cache = None
        self._tools_hash_cache = None

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名：{tool.name}")
        self._tools[tool.name] = tool
        self._invalidate_caches()

    def unregister(self, name: str) -> bool:
        """注销单个工具（与 register 对称），同样清派生缓存。"""
        if name not in self._tools:
            return False
        del self._tools[name]
        self._invalidate_caches()
        return True

    def unregister_prefix(self, prefix: str) -> list[str]:
        """按名称前缀批量注销（MCP 热卸载用：mcp__<server>__ 前缀一次摘除全部）。

        返回被移除的工具名列表。派生缓存只需清一次。
        """
        names = [n for n in self._tools if n.startswith(prefix)]
        if not names:
            return []
        for n in names:
            del self._tools[n]
        self._invalidate_caches()
        return names

    def __contains__(self, name: str) -> bool:
        """name 是否已注册。供 ToolSourceCoordinator 幂等替换判断。"""
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未注册的工具：{name}")
        return self._tools[name]

    def list(self, names: list[str] | None = None) -> list[Tool]:
        if names is None:
            return list(self._tools.values())
        return [self._tools[n] for n in names if n in self._tools]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def lc_tools_static(self) -> list[dict]:
        """只返回 disclosure=="static" 的工具（Anthropic 格式 dict），常驻绑定给模型。

        dynamic 工具（声明式 CLI / MCP）不在其中，需经 tool_search 披露后再由
        get() 按名取回绑定，并按工具集缓存。
        """
        if self._lc_tools_static_cache is None:
            self._lc_tools_static_cache = [
                t.to_langchain()
                for t in self._tools.values()
                if getattr(t, "disclosure", "static") == "static"
            ]
        return self._lc_tools_static_cache

    def get_langchain(self, names: list[str]) -> list[dict]:
        """按名解析为 langchain dict 列表；跳过未注册的名（如已热卸载的 MCP 工具）。

        tool_search 披露后 agent 节点用它取回已解锁工具的绑定定义；不缓存
        （disclosed 集因会话而异且不断变化，缓存收益低）。
        """
        return [t.to_langchain() for t in self.list(names)]

    def dynamic_specs(self) -> list[dict[str, str]]:
        """返回 dynamic 工具的检索元信息 [{name, description}]，供 tool_search 匹配。

        不缓存：dynamic 池通常很小，且 tool_search 调用频率远低于工具执行，
        实时枚举可避免又一层缓存失效维护。
        """
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
            if getattr(t, "disclosure", "static") == "dynamic"
        ]

    def match_dynamic(self, query: str, limit: int = 10) -> list[str]:
        """按 query 在 dynamic 工具的名称+描述上做简单子串/关键词匹配，返回命中工具名。

        单一匹配来源：tool_search 工具用它生成给模型看的清单，tool_node 用同一函数
        在同样的 (query, limit) 上复算命中集写回 disclosed_tools —— 二者结果必然一致，
        无需解析工具输出即可让"披露"与"可绑定"对齐。

        匹配规则（不做语义检索）：query 空 → 返回全部 dynamic（截到 limit）；否则
        按空白拆成关键词，任一关键词作为子串命中 name 或 description（均小写）即算命中。
        """
        specs = self.dynamic_specs()
        lim = max(1, limit)
        q = query.strip().lower()
        if not q:
            return [s["name"] for s in specs][:lim]
        terms = [t for t in q.split() if t]
        hits: list[str] = []
        for s in specs:
            haystack = f"{s['name']}\n{s['description']}".lower()
            if any(term in haystack for term in terms):
                hits.append(s["name"])
        return hits[:lim]

    def tools_hash(self) -> int:
        """工具集未变时返回稳定 hash（用作 bound_model_cache 键）。"""
        if self._tools_hash_cache is None:
            self._tools_hash_cache = hash(tuple(self._tools.keys()))
        return self._tools_hash_cache


registry = ToolRegistry()


def register(cls: type[T]) -> type[T]:
    """类装饰器：实例化并注册。"""
    registry.register(cls())
    return cls


def load_builtin_tools() -> None:
    """显式加载 builtin 工具（避免循环导入用 lazy 方式）。"""
    # noqa: F401 — 仅触发装饰器副作用
    from harness.tools.builtin.cmd import file_ops, knowledge, search, shell  # noqa: F401
    from harness.tools.builtin.orchestration import (  # noqa: F401
        load_skill,
        run_agent,
        tool_search,
    )
    from harness.tools.builtin.security import board as sec_board  # noqa: F401
    from harness.tools.builtin.security import engagement as sec_engagement  # noqa: F401
    from harness.tools.builtin.security import finding as sec_finding  # noqa: F401
    from harness.tools.builtin.security import report as sec_report  # noqa: F401
    from harness.tools.builtin.web import fetch as web_fetch  # noqa: F401
    from harness.tools.builtin.web import search as web_search  # noqa: F401
