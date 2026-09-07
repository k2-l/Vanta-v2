# Vanta 能力接入 Wiki

> 本 wiki 是 Vanta 五类能力（**skill · agent · tool · mcp · plugin**）的接入规范与示例。
> **真值永远在代码**——本文只做人类可读镜像，改协议时同步更新对应页。

## 两套协议

Vanta 的能力面沿两套正交协议组织。搞清一个能力属于哪套，就知道该怎么接：

| | **协议 A · 声明式能力** | **协议 B · 可执行动作** |
|---|---|---|
| 覆盖 | **skill · agent**（· knowledge） | **tool · mcp · plugin** |
| 回答 | “是谁 / 知道什么 / 能派给谁” | “能做什么” |
| 驱动 | **文件驱动**（markdown + frontmatter） | **代码 / 接入驱动**（实现或接入 `Tool`） |
| 落点 | `harness/contracts/`（`BaseFileProvider` + `EntityProvider` + `frontmatter`） | `harness/tools/`（`Tool` + `registry` + `ToolSource`/`coordinator`） |
| 加载 | `get_provider(kind)` 懒读文件，L1 清单注入 prompt | 三来源都产出 `Tool`，落进同一 `registry` |

**两者不是平行线——协议 A 通过协议 B 调度。** `Skill` / `Agent` / `load_agent` / `tool_search` 本身就是协议 B 里的工具：模型加载一个 skill = 调 `Skill` 工具把文件内容注入上下文；派一个 agent = 调 `Agent` 工具起子图。缝合点就这几个 orchestration 工具。

```
协议 A（文件驱动，声明能力）          协议 B（代码驱动，执行动作）
  workspace/skills/<name>/SKILL.md      harness/tools/builtin/**        ← tool
  workspace/agents/<name>/AGENT.md      [[mcp.servers]] 配置           ← mcp
        │                               plugins/<name>/get_tools()     ← plugin
        │  经 get_provider(kind) 加载             │  经 ToolSource → registry 接入
        └───────── 缝合点：Skill / Agent / load_agent / tool_search 工具 ─────────┘
                                （协议 A 挂在协议 B 上被调度）
```

## 能力速查

| 类型 | 协议 | 接入方式 | 页面 |
|---|---|---|---|
| **Skill** | A | 放 `workspace/skills/<name>/SKILL.md`，写 frontmatter + 正文 | [skill.md](./skill.md) |
| **Agent** | A | 放 `workspace/agents/<name>/AGENT.md`，写 frontmatter + system prompt | [agent.md](./agent.md) |
| **Tool** | B | 实现 `Tool` 基类 + `@register` | [tool.md](./tool.md) |
| **MCP** | B | 写 `[[mcp.servers]]` 配置 或 REST 挂载，零代码 | [mcp.md](./mcp.md) |
| **Plugin** | B | 放 `plugins/<name>/__init__.py` 暴露 `get_tools()` | [plugin.md](./plugin.md) |

## 关键源码入口

- 协议 A：`harness/contracts/base.py`（`BaseFileProvider`）· `harness/contracts/protocol.py`（`EntityProvider`）· `harness/providers.py`（`get_provider`）
- 协议 B：`harness/tools/base.py`（`Tool`/`ToolResult`）· `harness/tools/registry.py`（`registry`/`@register`）· `harness/tools/source.py`（`ToolSource`/`coordinator`）
- 缝合：`harness/tools/builtin/orchestration/`（`Skill` · `Agent` · `load_agent` · `tool_search`）
- 主循环：`harness/core/graph/`（`preprocess → agent → tools → recovery`，见对应 Agent Loop 对照图）
