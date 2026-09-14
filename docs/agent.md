# Agent 接入规范

**协议 A · 声明式能力 · 文件驱动。** Agent = 一个可被派遣的专家角色。经 `Agent` 工具派发后，它在**独立子图**里自带一套 `agent → tools → recovery` 循环执行，返回最终输出。

## 落点

```
{VANTA_ROOT}/workspace/agents/<name>/AGENT.md
```

`VANTA_ROOT` 默认 `~/Vanta`。目录名即 agent 名（可被 frontmatter `name` 覆盖）。

## 文件格式

`AGENT.md` = YAML frontmatter + markdown 正文（正文即该 agent 的 system prompt）：

```markdown
---
name: audit-analyst
description: 白盒深度安全分析专家。扫描阶段完成后，对可疑点做数据流追踪与可利用性判定。
tools: [shell, knowledge, finding, Skill]
model: claude-sonnet-4-6
disable-model-invocation: false
user-invocable: true
---

你是一名资深代码审计分析师。你的职责是：
- 对给定的可疑点做 sanitizer 有效性判断与数据流追踪
- 判定漏洞可利用性与严重性
- 只做需要判断力的分析，不做机械扫描

输出要求：……
```

### frontmatter 字段（对齐 Claude Code subagent）

| 字段 | 层 | 必填 | 说明 |
|---|---|---|---|
| `name` | L1 | 否 | 规范名，缺省用目录名 |
| `description` | L1 | **是** | 一句话职责。**常驻注入 prompt**，模型据此决定派不派 |
| `tools` | L2 | 否 | 该子 agent 的**可用工具白名单**；空 = 继承默认工具集 |
| `model` | L2 | 否 | 子 agent 用的模型 |
| `disable-model-invocation` | L1 | 否 | `true` = 不进模型 L1 目录，仅可手动/按名加载 |
| `user-invocable` | L1 | 否 | `false` = 从用户菜单隐藏（预留） |

正文即 system prompt，子图直接消费（`AgentFull.content`），无需其他标记。

## 调度：`Agent` 工具

模型调 `Agent` 工具派发子任务：

```jsonc
// Agent 工具入参
{
  "name": "audit-analyst",     // 必填：目标 agent 名（须 active）
  "task": "分析 UserController 的 SQL 注入可利用性",  // 必填：任务描述
  "context": "上游扫描发现的可疑点：……"  // 可选：串行依赖时传上游输出
}
```

- **同一轮多个 `Agent` 调用并行执行**；需要串行时用 `context` 把前一个结果喂给后一个。
- 只能派 **active（已启动）** 的 agent。
- 见 `harness/tools/builtin/orchestration/run_agent.py`。

## 子图与主图的区别

派发后跑的是 `build_sub_graph()` 编译的独立图（`harness/core/graph/subagent/`）：

- **无 `preprocess`**——子 agent 不加载记忆/画像/skill 上下文，从任务描述干净起步。
- 工具按 `AGENT.md` 的 `tools` 白名单过滤。
- 自带 `agent → [tools → agent]* → recovery` 循环，可选挂 **critic 质量门**。
- 循环上限 `sub_agent_max_tool_iterations`（默认 10，内部有界委托护栏）；主/子代理均可委派，每个 invocation 最多同时运行 3 个直接子代理，完成后释放配额，派发深度 `sub_agent_max_depth` 默认为 3。
- 主代理与每个子代理 invocation 使用独立 token 预算；session/day 额度仅作为全局硬熔断与累计记账。

> 对比：主图工具循环默认 20 步，子 agent 循环默认 10 步；两者还分别受 invocation 独立 token 预算约束。

## `load_agent`：只取角色不派发

`load_agent` 工具（`{name}`）只加载 agent 的 L2 元数据（描述 + 允许工具），**不起子图**——供模型"以某角色视角"思考而无需真正派发。

## 新增一个 agent

1. 建目录 `workspace/agents/<name>/`，写 `AGENT.md`（frontmatter `description` + 正文 system prompt）。
2. 无需改代码、无需重启（provider 30s TTL 自刷新 / CRUD 触发 reload）。
3. 确保 agent 为 active，模型即可在 L1 清单看到并派发。

## 注意

- `description` 决定模型派不派，**写清"何时该派给它"**。
- `tools` 白名单是子 agent 的能力边界——主代理专属工具不在白名单里就调不到。
- 加载器 `get_provider("agent")` 见 `harness/agents/provider.py`（继承 `BaseFileProvider`）。
