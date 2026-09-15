# Vanta — 单兵作战 AI Agent 平台

单兵作战 AI Agent 编排平台，支持多 Agent 协同、技能按需加载、经验记忆、实时 Task 推送。能力沿**两套协议**组织：**声明式能力**（skill / agent，文件驱动）与**可执行动作**（tool / mcp / plugin，统一接入）。

---

## 架构

```
desktop/  Tauri 2 + React（WebView 只访问受控 Rust IPC）
  └─ Rust Core → SSE / REST → harness
harness/  Python / FastAPI (:8765)   编排、对话、管理 API 与容器/podman
workspace/                           Agent / Skill 文件及工具工作目录
```

单一 Python 后端 + PostgreSQL，JWT（HS256）鉴权（harness 用 `[auth] secret` 签发/校验 token）。

---

## 文档

能力接入规范与示例见 **[docs/ 能力接入 Wiki](./docs/README.md)**：

- [skill.md](./docs/skill.md) · [agent.md](./docs/agent.md) — 声明式能力（协议 A，文件驱动）
- [tool.md](./docs/tool.md) · [mcp.md](./docs/mcp.md) · [plugin.md](./docs/plugin.md) — 可执行动作（协议 B，统一接入）
- [Tauri Desktop GUI 定稿规范](./docs/tauri-desktop-gui-spec.md) · [实施 Plan](./docs/tauri-desktop-implementation-plan.md)

---

## 快速启动

配置集中在 `data/config.toml`（填写 `[anthropic] api_key`、`[auth] password/secret`、`[database] url` 等）。
基本对话只依赖模型服务和 PostgreSQL；Qdrant 是知识库与可选长期记忆的向量服务，
未配置 `[qdrant]` 时自动记忆/召回会跳过，不影响回答落库和 SSE 完成。

```bash
# 后端（FastAPI :8765）
uv run harness-api
# 桌面客户端（通过 Tauri Rust Core 连接后端）
cd desktop && npm install && npm run tauri:dev
```

代码检查：后端 `uv run ruff check harness tests`；桌面端 `cd desktop && npm test && npm run build`。

---

## 目录说明

| 目录 | 说明 |
|------|------|
| `harness/core/` | LangGraph 图/节点、协调器、记忆、Token 预算、子图、运行时 |
| `harness/routes/` | 所有 HTTP endpoint（chat / sessions / skills / agents / knowledge / containers / workspace / config / mcp / ws） |
| `harness/agents/`·`harness/skills/` | 协议 A 领域模块：加载 / 注册 / frontmatter |
| `harness/contracts/` | 协议 A 底座：`BaseFileProvider` · `EntityProvider` · frontmatter（agent/skill 共用的文件驱动契约） |
| `harness/infra/` | SQLAlchemy、向量库（Qdrant Cloud）、EventBus、JWT、settings、podman |
| `harness/security/` | 护栏：engagement / 沙箱 / 审计 / 脱敏 / 加密库 / 权限 |
| `harness/tools/` | 协议 B：工具基类·注册表·统一来源协议（`ToolSource`）；builtin/{cmd,security,web,orchestration} · mcp · sources/plugin |
| `harness/app/` + `harness/main.py` | FastAPI 装配 + 启动入口 |
| `workspace/` | Agent / Skill Markdown 与受控工具工作目录 |
| `data/` | `config.toml` 运行时配置（向量库用 Qdrant Cloud，无本地 chroma） |

---

## Workspace 文件格式

Agent / Skill 是文件驱动的（协议 A）：`workspace/agents/<name>/AGENT.md`、`workspace/skills/<name>/SKILL.md`，均为 YAML frontmatter + markdown 正文。

```markdown
---
name: java-audit
description: Java 代码安全审计的标准流程。任务涉及 Java 源码审计时加载。
allowed-tools: [shell, knowledge, finding]   # skill 字段；agent 用 tools
argument-hint: "传入目标代码路径"            # skill 专属
model: claude-sonnet-4-6
disable-model-invocation: false
---

## 步骤
1. ...
```

字段完整说明与示例见 [docs/skill.md](./docs/skill.md) / [docs/agent.md](./docs/agent.md)。

---

## 关键配置

以 `data/config.toml` 为主；同名 `HARNESS_*` 环境变量可覆盖。

| 配置 | 说明 |
|------|------|
| `[anthropic] api_key` | LLM 凭据；第三方兼容服务再加 `base_url` |
| `[auth] password` | 登录密码 |
| `[auth] secret` | JWT 签名密钥 |
| `[database] url` | PostgreSQL DSN |
| `[models] high/mid/low` | 三档模型（推理 / 默认 / 摘要标题） |
| `[paths] suite_dir` | workspace 套件根；相对路径按仓库根解析，启动时创建 agents/skills 子目录；留空默认 `workspace/` |
