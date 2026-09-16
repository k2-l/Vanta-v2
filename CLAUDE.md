# CLAUDE.md

## 1. 项目概览

**Vanta** — 授权范围内的**单兵作战 Agent 平台**（代码审计 / 侦察 / 渗透），构建在通用多 Agent 编排底座上（LangGraph 多 Agent 协同、技能按需加载、经验记忆、实时 Task 推送）。能力沿**两套协议**组织：**文件驱动协议**（声明式能力：agent / skill，`contracts/`）与**工具接入协议**（可执行动作：tool / mcp / plugin，统一 `ToolSource` 接入，`tools/`）。**单一 Python 后端** + Tauri 桌面客户端 + PostgreSQL，JWT（HS256）鉴权：

| 服务 | 技术栈 | 端口 | 职责 | 通信 |
|------|--------|------|------|------|
| `harness/` | Python / FastAPI | 8765 | LangGraph 编排与对话 + 管理 CRUD + 容器/podman | SSE / WebSocket / REST |
| `desktop/` | Tauri 2（Rust Core）+ React + Vite | 5180（Vite dev，HMR 5181） | 桌面客户端 UI；WebView 只经受控 Rust IPC 访问后端 | Rust IPC → SSE / REST |

## 2. 目录地图

| 目录 | 说明 |
|------|------|
| `harness/core/` | LangGraph 编排核心：`graph/`（图构建 `build`·节点 `nodes/`·路由 `routes`·子 agent `subagent/`·`tool_exec`）·`context/`（Token 预算·上下文构建·摘要压缩·用量）·`foundation/`（状态·事件·错误·registry·tokens·internal_sections）·`capabilities/`（memory·services）·`runtime.py`（`AgentRuntime`：会话锁/并发信号量/自动记忆） |
| `harness/contracts/` | **文件驱动协议底座**（声明式能力）：`BaseFileProvider`·`EntityProvider` 协议·`frontmatter`·`models`·`render`，agent 与 skill 共用的文件驱动契约 |
| `harness/agents/`·`harness/skills/` | 文件驱动协议领域实现：各自 `provider.py`（继承 `BaseFileProvider`）；统一经 `harness/providers.py` 的 `get_provider(kind)`（组合根 / 服务定位器，缓存单例）取用 |
| `harness/routes/` | 所有 HTTP endpoint（chat / sessions / skills / agents / knowledge / containers / board / memories / config / mcp / budget / ws；`_utils` 共享助手） |
| `harness/infra/` | 地基：`db`（SQLAlchemy + asyncpg）、`vector`（Qdrant Cloud）、`event_bus`、JWT、`settings`/`config_store`、`fetcher`（URL 抓取）、`podman`（容器 CLI 封装）、`logging`/`metrics`/`retry`/`profile` |
| `harness/security/` | **安全护栏**：`engagement`(scope/RoE)、`sandbox`(egress 锁定沙箱)、`audit_ledger`(哈希链审计)、`redaction`(凭据脱敏)、`secrets_vault`/`output_vault`+`vault_paths`、`permissions`/`approvals`/`audit_agent` |
| `harness/tools/` | **工具接入协议底座**（可执行动作）：`base`·`registry`·`sanitizer`·`exec_context`·`source`(`ToolSource`)；`sources/{builtin,plugin}`；`builtin/{cmd,orchestration,security,web}`；`mcp/`(MCP stdio 客户端 + 热加载管理器) |
| `harness/app/` + `harness/main.py` | FastAPI 装配（`create_app`/`lifespan`/中间件/`auth`/`schemas`，`/health`·`/metrics`·`/profile`）+ 启动入口 `run()` |
| `desktop/src/` | React 前端（`app/` shell+router+moduleNavigation、`features/<domain>/`(chat·runs·approvals·artifacts·capabilities·connection)、`components/`、`contracts/`(与后端事件/资源/流契约)、`ipc/`、`stores/`、`hooks/`、`pages/`） |
| `desktop/src-tauri/` | Rust Core（`backend_gateway`·`commands`·`connections`·`credentials`·`diagnostics`·`state`），WebView 访问后端的唯一受控出口 |
| `workspace/` | 运行时套件目录（`[paths] suite_dir`，默认 `workspace/`，已 gitignore）：agents / skills / knowledge / containers 的 Markdown |
| `data/` | 运行时配置 `config.toml` / `config.json` + 用户/助手画像 `profile.md`（向量库已上云 Qdrant，无本地 `chroma/`） |
| `docs/` | 能力接入规范（`skill`/`agent`/`tool`/`mcp`/`plugin`）+ Tauri 桌面 GUI 规范与实施 plan |
| `tests/` | 少量后端逻辑测试（`unittest`）：chat 后端降级韧性 + 编排 remediation（含「每个桌面操作都有后端路由」契约校验） |


## 3. 开发环境与运行方式

**后端**：运行 `uv run harness-api`（FastAPI :8765，需先起 PostgreSQL）；lint `uv run ruff check harness tests`（或 `uvx ruff check` / `uvx ruff format`）；逻辑单测 `uv run python -m unittest discover -s tests`（裸 `.venv` 缺依赖，必须走 `uv run`）。
**桌面端**：全量 `cd desktop && npm install && npm run tauri:dev`（需 Rust / Tauri Linux 开发库）；仅 WebView `npm run dev`（Vite :5180）；测试 `npm test`（vitest）；构建 `npm run build`（tsc -b + vite build），桌面产物 `npm run tauri:build`；eslint `npm run lint`。


## 4. 代码风格

> Python lint 本地即可跑（`uvx ruff`）；桌面端检查直接跑（`npm`）。

- **Python**：ruff（line-length 100，规则 `E/F/W/I/B/UP/ASYNC`，忽略 `E501`）+ mypy。改完本地跑 `uvx ruff check` / `uvx ruff format`。
- **桌面端**：TypeScript strict + eslint（`npm run lint`）+ Tailwind CSS；Rust Core 走 `cargo`（`src-tauri/`）。

## 5. Git 与提交规范

- **提交信息**：conventional 前缀 `feat:` / `fix:` / `chore:`；描述中英文皆可，多项变更用 `+` 连接，补充说明用 `—`。
- **分支**：直接提交到当前工作分支（现为 `Bate-v1`），提交需用户明确发话，push 另行确认。

## 6. 工作流原则

- **测试**：仓库维护少量后端逻辑测试（`tests/`，`unittest`，含桌面↔后端契约校验）；新增自测按同风格追加，跑法见 §3。
- **代码查询优先用 Codegraph MCP**（`codegraph_*` 工具）做结构性查询（定义 / 调用 / 影响 / trace）；codegraph 无法覆盖时再用 grep、sed、awk、find。初始化：`codegraph init -i`（一步完成 init + index）。
- **任务派发（团队约定）**：实质 / 可并行 / 独立的活派发给子 agent；跨文件统一、快改、需紧控质量的活主代理直接做。

## 7. 对话规则

- **语言**：全程使用简体中文。
