# Tool 接入规范

**协议 B · 可执行动作 · 代码驱动。** Tool = 模型能真正"做事"的最小可执行单元。builtin / MCP / plugin 三类来源**最终都产出 `Tool`**，落进同一个 `registry`，由 `tool_node` 统一执行。本页讲**内置工具**（写代码接入）；MCP / plugin 见各自页。

## 基类：`Tool`

在 `harness/tools/base.py`。实现一个内置工具 = 继承 `Tool` 并实现 `run`：

```python
from typing import Any
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register


@register
class WhoisTool(Tool):
    name = "whois"
    description = "查询域名的 WHOIS 注册信息。传入 domain，返回注册商/创建时间/联系人等。"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "要查询的域名，如 example.com"},
        },
        "required": ["domain"],
    }
    category = "web"          # 分类，纯元数据（见下）
    disclosure = "static"     # 常驻绑定给模型；"dynamic" 则藏在 tool_search 之后
    requires_approval = False # True 则执行前走 HITL 审批门

    async def run(self, domain: str) -> ToolResult:
        try:
            out = await _do_whois(domain)          # 你的实现
            return ToolResult(ok=True, output=out)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(f"whois 失败：{exc}", error_code="WHOIS_FAILED")
```

### 类属性

| 属性 | 必填 | 说明 |
|---|---|---|
| `name` | **是** | 全局唯一工具名（重名 `register` 抛错） |
| `description` | **是** | 给模型看的用途；写清入参与产出 |
| `input_schema` | **是** | JSON Schema，直接给 `bind_tools`（**别靠 `**kwargs` 推断**，否则 LLM 拿到空 schema） |
| `category` | 否 | `exec`（默认）`file` `skill` `agent` `mcp` `orchestration` `knowledge` `runtime`——分类展示用，不改行为 |
| `disclosure` | 否 | `static`（默认，常驻绑定）/ `dynamic`（藏在 `tool_search` 之后按需披露，抑制 prompt 膨胀，适合工具多的场景） |
| `requires_approval` | 否 | `True` = 执行前需人工/审计 agent 审批；配 `approval_message` 文案 |

### `run` 与 `ToolResult`

`async def run(self, **kwargs) -> ToolResult`，入参对应 `input_schema`。返回：

| 字段 | 说明 |
|---|---|
| `ok` | 成功与否 |
| `output` | 给模型的文本结果 |
| `error` | 失败描述 |
| `error_code` | 结构化错误码，供 `recovery_node` 精确路由（如 `TIMEOUT`/`COMMAND_NOT_FOUND`） |
| `artifacts` | 可选结构化产物 |

快捷失败：`ToolResult.fail("原因", error_code="XXX")`。

## 注册

1. `@register` 装饰器实例化并注册进全局 `registry`（import 时生效）。
2. 把模块加进 `harness/tools/registry.py::load_builtin_tools()` 的 import 列表（触发装饰器）。
3. 放在 `harness/tools/builtin/<category>/<name>.py`（cmd / web / security / orchestration…）。
4. 工具名是稳定协议，重命名时同步迁移 Agent/Skill 配置；后端不保留隐式旧名别名。

## 执行时会经过什么（`tool_node`）

内置工具被调用时，`harness/core/graph/nodes/tools.py` + `tool_exec.py` 统一处理：

- **并发执行**本轮所有 tool_call（`tool_concurrency` 信号量限流；单轮数量默认不限）；
- **per-tool 超时** `tool_timeout_seconds` + 输出截断 `max_tool_output_chars`；
- **权限/审批门**：`permissions.evaluate` 策略 + `requires_approval` 的 HITL/审计 agent 复核；
- **scope 门**：叠加会话活跃 engagement，主动扫描类动作受授权范围约束；
- **失败计数**：某工具累计失败超阈值，注入提示让模型换工具；
- 结果包成 `ToolMessage` 回灌，供模型下一轮"观察"。

## 动态披露（`tool_search`）

`disclosure="dynamic"` 的工具不常驻绑定，模型需先用 `tool_search` 按关键词搜到、披露后下一轮才可调用。命中的工具名写回 `disclosed_tools`（跨轮去重累积）。适合 MCP / 大量声明式工具，避免 prompt 里工具定义膨胀。

## 注意

- `name` 必须全局唯一；`input_schema` 必须显式写全，否则模型生成错误参数。
- 危险动作设 `requires_approval=True`；破坏性/外发操作交给审批门，别在 `run` 里裸执行。
- 只读、确定性工具可考虑接入缓存（见 `tool_node` 的 `CACHEABLE_TOOLS`）。
