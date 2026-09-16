# Plugin 接入规范

**工具接入协议 · 可执行动作 · 接入驱动。** Plugin 是**新的可插拔工具来源**：一个本地包，暴露 `get_tools()` 工厂产出 `Tool` 列表。它与 builtin / MCP 走**同一套 `ToolSource` 接入协议**——加一个来源 = 实现一个方法，不改 harness 任何代码。

## 落点与开关

```
{plugins_dir}/<name>/__init__.py     # 暴露 get_tools() -> list[Tool]
```

配置（`harness/infra/settings.py`）：

| 设置 | 默认 | 说明 |
|---|---|---|
| `plugins_enabled` | `false` | 总开关。`true` 才在启动时扫描挂载 |
| `plugins_dir` | `"plugins"` | 插件根目录 |

默认关闭：不填 `plugins_enabled=true` 时 `load_plugins()` 直接跳过，零行为影响。

## 插件契约

一个插件是 `{plugins_dir}/<name>/` 下的 Python 包，其 `__init__.py` 暴露：

```python
# plugins/recon_extra/__init__.py
from typing import Any
from harness.tools.base import Tool, ToolResult


class SubfinderTool(Tool):
    name = "subfinder"
    description = "被动子域名枚举。传入 domain，返回发现的子域名列表。"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"domain": {"type": "string", "description": "目标主域名"}},
        "required": ["domain"],
    }
    category = "web"
    disclosure = "dynamic"   # 插件工具建议 dynamic，经 tool_search 按需披露

    async def run(self, domain: str) -> ToolResult:
        out = await _run_subfinder(domain)
        return ToolResult(ok=True, output=out)


def get_tools() -> list[Tool]:
    """插件入口：返回本插件提供的 Tool 实例列表。"""
    return [SubfinderTool()]
```

- 返回的每个对象须是 `Tool` 子类实例（规范同 [tool.md](./tool.md)）；非 `Tool` 的会被过滤掉。
- 插件工具**由协调器统一注册**，无需自己 `@register`（那是 builtin 编译期自注册用的）。

## 生命周期

```
启动 → load_plugins()（plugins_enabled 时）
  → discover_plugin_sources() 扫 plugins_dir 下每个含 __init__.py 的子目录
  → 每个包 = 一个 PluginSource(ToolSource)，id = plugin:<name>
      discover() → import 包 → 调 get_tools() → 返回 Tool 列表
  → ToolSourceCoordinator 注册进全局 registry（记录 name→source 归属）
```

单个插件加载失败只记 status=error、隔离，不影响其余插件与主服务。见 `harness/tools/sources/plugin.py`。

## 与 builtin / MCP 的关系

三者共用 `harness/tools/source.py` 的 `ToolSource` 协议：

| 来源 | `ToolSource` 实现 | 产出方式 | 卸载 |
|---|---|---|---|
| builtin | `BuiltinSource`（`self_registers=True`） | `@register` 装饰器 import 时注册 | 静态常驻，不卸载 |
| mcp | `MCPSource`（每 server 一个） | `discover()` 拉子进程 + `tools/list` | 热卸载 + drain |
| **plugin** | **`PluginSource`（每包一个）** | **`discover()` 调 `get_tools()`** | 卸载即摘工具 |

协调器还提供 `reload(source_id)` 热重载能力，将来给前端加"重载插件"按钮可直接用。

## 新增一个插件（清单）

1. 建 `{plugins_dir}/<name>/__init__.py`，实现若干 `Tool` 子类 + `get_tools()`。
2. 配置 `plugins_enabled = true`（首次启用时）。
3. 重启（或将来经 `coordinator.reload` 热载）——工具以插件名归属出现在 registry。

## 注意

- 插件代码在**本进程内**执行，等同信任内置工具——只放你信任的来源，勿加载不可信第三方包。
- 插件工具同样受执行层的超时 / scope / 审批门约束（在 `tool_node` 统一施加）。
- 工具名全局唯一，注意别与 builtin / 其他插件撞名。
