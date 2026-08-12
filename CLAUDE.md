# CLAUDE.md

## 1. 项目概览

**Vanta** — 授权范围内的**单兵作战 Agent 平台**（代码审计 / 侦察 / 渗透），构建在通用多 Agent 编排底座上（多 Agent 协同、技能按需加载、经验记忆、实时 Task 推送）。**单一 Python 后端** + React 前端 + 共享 PostgreSQL，JWT（HS256）鉴权：

| 服务 | 技术栈 | 端口 | 职责 | 前端通信 |
|------|--------|------|------|----------|
| `harness/` | Python / FastAPI | 8765 | 编排与对话 + 管理 CRUD + 容器/podman | SSE / WebSocket / REST |
| `web/` | React + Vite | 5173 | 前端 UI | — |

## 2. 目录地图

| 目录 | 说明 |
|------|------|
| `harness/core/` | 编排核心：图/节点、协调器、上下文/Token 预算、记忆、子图、运行时（`graph/`·`context/`·`foundation/`·`capabilities/`·`runtime.py`） |
| `harness/agents/`·`harness/skills/` | 领域模块：agent/skill 加载·注册·frontmatter（供 `routes/` + `core/graph` 调用） |
| `harness/routes/` | 所有 HTTP endpoint（chat / sessions / skills / agents / knowledge / containers / workspace-sync / config / mcp / budget / ws） |
| `harness/infra/` | 地基：SQLAlchemy(`db`)、向量库（Qdrant Cloud）、EventBus、JWT、settings、依赖解析器、URL 抓取器 `fetcher.py`、`podman.py`(容器 CLI 封装)、config_store |
| `harness/security/` | **安全护栏**：`engagement`(scope/RoE)、`sandbox`(egress 锁定沙箱)、`audit_ledger`(哈希链审计)、`redaction`(凭据脱敏)、`secrets_vault`/`output_vault`+`vault_paths`、`permissions`/`approvals`/`audit_agent` |
| `harness/tools/` | 工具基类、注册表、沙箱、执行上下文；`builtin/{cmd,security,web}`；`harness/tools/mcp/` 为 MCP stdio 客户端 + 热加载管理器 |
| `harness/app/` + `harness/main.py` | FastAPI 装配（create_app/中间件/lifespan/auth/schemas）+ 启动入口 `run()` |
| `web/src/` | React 前端（`app/` 应用壳+路由、`features/<domain>/`、`shared/`、`store/`） |
| `workspace/` | Markdown 文件（agents / skills / knowledge / containers） |
| `data/` | 运行时配置 `config.toml` / `config.json` + 用户/助手画像 `profile.md`（向量库已上云 Qdrant，无本地 `chroma/`） |


## 3. 开发环境与运行方式

**后端**：（运行`uv run harness-api`）、（检查`uvx ruff`）（逻辑单测`uv run --python 3.12 --no-project`）
**前端**：（运行`cd web && npm install && npm run dev`）、（构建`cd web && npm run build`）、（eslint`cd web && npm run lint`）


## 4. 代码风格

> Python lint 本地即可跑（`uvx ruff`）；Web 检查直接跑（`npm`）。

- **Python**：ruff（line-length 100，规则 `E/F/W/I/B/UP/ASYNC`，忽略 `E501`）+ mypy。改完本地跑 `uvx ruff check` / `uvx ruff format`。
- **Web**：TypeScript strict + eslint（`npm run lint`）+ Tailwind v4。

## 5. Git 与提交规范

- **提交信息**：conventional 前缀 `feat:` / `fix:` / `chore:`；描述中英文皆可，多项变更用 `+` 连接，补充说明用 `—`。
- **分支**：直接提交到 `Vanta-v2`分支，提交需用户明确发话，push 另行确认。

## 6. 工作流原则

- **测试**：仓库不维护自动化测试套件（`tests/` 已移除）；如需自测按需临时添加、不入库。
- **代码查询优先用 Codegraph MCP**（`codegraph_*` 工具）做结构性查询（定义 / 调用 / 影响 / trace）；codegraph 无法覆盖时再用 grep、sed、awk、find。初始化：`codegraph init -i`（一步完成 init + index）。
- **任务派发（团队约定）**：实质 / 可并行 / 独立的活派发给子 agent；跨文件统一、快改、需紧控质量的活主代理直接做。
