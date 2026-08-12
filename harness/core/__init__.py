"""harness.core — L2 多 Agent 编排核心（Supervisor + Worker + Critic 拓扑）。

公共 API（对外只从本包顶层导入这些；带 `_` 前缀的子模块成员一律视为私有实现，
不应被 harness.core 之外的代码直接 import）：

    AgentRuntime                                    —— 对话运行时入口（routes.chat）
    run_sub_agent                                   —— 派发子 agent 执行（Agent 工具）
    current_sub_agent_depth / enter_sub_agent_depth —— 子 agent 递归深度（Agent 工具）
    load_agent_content                              —— 加载单个 Agent 定义（Agent 工具）
    clear_model_caches                              —— 配置变更后清模型缓存（infra.config_store）

域内 API 仍从各包导入：foundation / context / graph + capabilities（skills·agents·memory·services）。
惰性 __getattr__ 转发，避免「导入本包」就拉起整个运行时图（保持 import 轻量、规避循环）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "AgentRuntime",
    "clear_model_caches",
    "current_sub_agent_depth",
    "enter_sub_agent_depth",
    "load_agent_content",
    "run_sub_agent",
]

# name -> (module, attr) 惰性转发表
_PUBLIC: dict[str, tuple[str, str]] = {
    "AgentRuntime": ("harness.core.runtime", "AgentRuntime"),
    "run_sub_agent": ("harness.core.graph.subagent", "run_sub_agent"),
    "current_sub_agent_depth": ("harness.core.graph.subagent", "current_sub_agent_depth"),
    "enter_sub_agent_depth": ("harness.core.graph.subagent", "enter_sub_agent_depth"),
    "load_agent_content": ("harness.agents.loader", "load_agent_content"),
    "clear_model_caches": ("harness.core.graph.models", "clear_model_caches"),
}

if TYPE_CHECKING:  # 仅供类型检查器解析，运行时走 __getattr__
    from harness.agents.loader import load_agent_content
    from harness.core.graph.models import clear_model_caches
    from harness.core.graph.subagent import (
        current_sub_agent_depth,
        enter_sub_agent_depth,
        run_sub_agent,
    )
    from harness.core.runtime import AgentRuntime


def __getattr__(name: str):  # PEP 562 惰性属性
    target = _PUBLIC.get(name)
    if target is None:
        raise AttributeError(f"module 'harness.core' has no attribute {name!r}")
    import importlib

    module, attr = target
    return getattr(importlib.import_module(module), attr)
