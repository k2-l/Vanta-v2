# Vanta — 单兵作战 AI Agent 平台

单兵作战 AI Agent 编排平台，支持多 Agent 协同、技能按需加载、经验记忆、实时 Task 推送。能力沿**两套协议**组织：**声明式能力**（skill / agent，文件驱动）与**可执行动作**（tool / mcp / plugin，统一接入）。

---

## 架构

```
web/ (React + Vite, :5173)
  └─ SSE / WebSocket / REST → harness
harness/   (Python / FastAPI, :8765)   编排与对话 + 管理 CRUD + 容器/podman
workspace/                              Agent / Skill / Knowledge 文件
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
# 前端开发（Vite dev server :5173，连后端 :8765）
cd web && npm install && npm run dev
```

代码检查：后端 `uvx ruff check` / `uvx ruff format`；前端 `cd web && npm run lint`。

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
| `workspace/` | Markdown 文件（agents / skills / knowledge / containers） |
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
