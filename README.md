# Vanta — 单兵作战 AI Agent 平台

单兵作战 AI Agent 编排平台，支持多 Agent 协同、技能按需加载、经验记忆、实时 Task 推送。

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

## 快速启动

配置集中在 `data/config.toml`（首次从 `data/config.toml.example` 复制填写）。

```bash
# 1. 准备配置：填写 [anthropic] api_key、[auth] password/secret、[database] url 等
cp data/config.toml.example data/config.toml
# 2. 前端开发（Vite dev server :5173，连后端 :8765）
cd web && npm install && npm run dev
```

---

## 目录说明

| 目录 | 说明 |
|------|------|
| `harness/core/` | LangGraph 图/节点、协调器、记忆、Token 预算、子图、运行时 |
| `harness/routes/` | 所有 HTTP endpoint（chat / sessions / skills / agents / knowledge / containers / workspace / config / mcp / ws） |
| `harness/agents/`·`harness/skills/` | 领域模块：加载 / 注册 / frontmatter |
| `harness/infra/` | SQLAlchemy、向量库（Qdrant Cloud）、EventBus、JWT、settings、podman |
| `harness/security/` | 护栏：engagement / 沙箱 / 审计 / 脱敏 / 加密库 / 权限 |
| `harness/tools/` | 工具基类、注册表、沙箱、执行上下文；builtin/{cmd,security,web} + mcp |
| `harness/app/` + `harness/main.py` | FastAPI 装配 + 启动入口 |
| `workspace/` | Markdown 文件（agents / skills / knowledge / containers） |
| `data/` | `config.toml` 运行时配置（向量库用 Qdrant Cloud，无本地 chroma） |

---

## Workspace 文件格式

```markdown
---
name: java-audit
description: Java 代码安全审计
trigger: audit java
argument_hint: "target_path: 项目路径"
dependencies:
  - inrepository: owasp-top10
---

## 执行流程
...
```

---

## 关键配置

以 `data/config.toml` 为主（见 `config.toml.example`）；同名 `HARNESS_*` 环境变量可覆盖。

| 配置 | 说明 |
|------|------|
| `[anthropic] api_key` | LLM 凭据；或 `auth_token`；第三方兼容服务再加 `base_url` |
| `[auth] password` | 登录密码 |
| `[auth] secret` | JWT 签名密钥 |
| `[database] url` | PostgreSQL DSN |
| `[models] high/mid/low` | 三档模型（推理 / 默认 / 摘要标题） |
| `[paths] suite_dir` | workspace 路径（默认 `workspace`） |
