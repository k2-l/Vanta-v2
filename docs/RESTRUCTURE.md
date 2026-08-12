# Vanta 后端重构施工图

> **目标**：合并 nexus 独立服务 → **单一 Python 后端**；按领域/层次重组 harness 目录，收敛「读→nexus / 写→harness」的劈叉与跨语言重复 schema。产出更清爽、贴合「能力 = 编排」定位的结构。
>
> 本文件是迁移的**照表施工依据**。未 commit —— 随重构一并提交。

## 1. 背景 / 为什么

- **现状**：harness(Python) + nexus-svc(Go) 两后端共享 PostgreSQL。agents/skills/kb 的 ORM 模型在 harness `db.py`，但 nexus 也读同一批表 → **表结构在 Python 和 Go 里各存一份**。前端读走 nexus:8766、写走 harness:8765 → **同一个实体劈在两个后端**（nexus 一挂，管理页即废——已实测踩过）。
- **决定**：**nexus 并入 harness**，管理 CRUD 收回 Python；harness 内部按第 2 节结构重组。
- **原则**：能力(agents/skills/kb/mcp) = 编排底座，不写固定流水线；护栏(`security/`)是代码强制的安全底板；`infra/` 是全局地基。

## 2. 目标结构

```
Vanta/
├─ harness/                              # 唯一后端（Python，nexus 并入）
│  ├─ main.py                            # 入口（uvicorn.run）
│  ├─ app/                               # FastAPI 装配：create_app·中间件·lifespan·auth·schemas
│  ├─ routes/                            # 所有 HTTP endpoint（水平层，统一放）
│  ├─ infra/                             # 地基：db·settings·jwt·vector·event_bus·logging·anthropic·config_store·fetcher·retry·metrics·resolver·deps
│  ├─ core/                              # 编排核心（原 agent/，改名避开 langgraph 库）
│  │  ├─ graph/  context/  foundation/  runtime.py
│  ├─ agents/  skills/  knowledge/  mcp/ # 领域逻辑（水平层：只逻辑；CRUD·加载·frontmatter，并入 nexus 读写）
│  ├─ tools/                             # base·registry·exec_context·sanitizer + builtin/{cmd,security,web} + mcp client
│  └─ security/                          # 护栏：engagement/scope·sandbox(egress)·audit_ledger·redaction·secrets/output_vault·vault_paths·permissions·approvals·audit_agent
├─ web/                                  # 前端（api.ts 去 nexus base，只连 :8765）
├─ data/
│  ├─ config.toml · profile.md
│  └─ workspace/                         # 用户 agent/skill/kb/mcp（.md）
└─ logs/
```

### 分层约定
- **水平分层**：`agents/`·`skills/`·`knowledge/`·`mcp/` 只放**领域逻辑**（CRUD·加载·frontmatter），HTTP endpoint 统一在 `routes/`。
- `infra/` 提到顶层（不埋核心，因全局共用）；`core/` 是编排核心（原 `agent/`，改名避开三方库 `langgraph`）；`security/` 收编护栏。
- **两个 sandbox 别混**：egress 网络沙箱在 `security/`；工具执行上下文在 `tools/`。

## 3. 迁移映射 —— harness 内部

| 现在 | → 去向 |
|---|---|
| `api/main.py`(run) | `main.py` |
| `api/main.py`(create_app/中间件/lifespan) + `api/{auth,schemas}.py` | `app/` |
| `agent/{graph,context,foundation}/` + `agent/runtime.py` | `core/`（同名子目录） |
| `agent/capabilities/{agents,skills}.py` | 并入领域模块 `agents/`·`skills/`（见 §5·④） |
| `agent/capabilities/{memory,services,utils}.py` | `core/`（memory→context；services=titler 类杂务；utils→core util） |
| `infra/{engagement,sandbox,audit_ledger,redaction,secrets_vault,output_vault,vault_paths,permissions,approvals,audit_agent}.py` | **`security/`** |
| `infra/nexus_client.py` | **删**（同进程，客户端作废） |
| `infra/` 其余（db·settings·vector·event_bus·logging·anthropic·config_store·fetcher·retry·metrics·resolver·deps） | 留 `infra/` |
| `routes/*`（agents·budget·chat·config·internal·knowledge·mcp·memories·sessions·skills·ws·_utils） | 留 `routes/`（agents/skills/knowledge/mcp 变读+写全 CRUD） |
| `tools/*` | 留 `tools/`（空目录 `builtin/hook/` 删） |

## 4. 迁移映射 —— nexus-svc 并入（Go → Python 端口 + 丢冗余层）

| nexus | → |
|---|---|
| `handlers/{agent,skill,kb}.go` | 端口进 `routes/{agents,skills,knowledge}.py`(读侧) + 领域模块逻辑 |
| `handlers/container.go` + `services/podman.go` | `routes/containers.py` + 容器逻辑（harness 已有 podman 通路） |
| `handlers/workspace.go` + `services/{workspace,file_watcher,indexer}.go` | workspace 文件 I/O·frontmatter·监听·索引 → Python（领域模块 / infra） |
| `models/*` · `db/*` · `middleware/jwt.go` · `config/config.go` · `routes/routes.go` · `main.go` · `services/{harness_notify,noop}.go` | **全删**（harness 的 db.py / app / infra 已覆盖；schema 归一到 db.py） |

**合并实质** = 把 Go 的「读侧 CRUD + workspace 文件监听/frontmatter + podman 容器管理」端口成 Python，其余（models/db/jwt/config/routes/main）全丢——harness 早有对应。真正工作量在这块 Python 化，不是无脑搬。

## 5. 已定的两个点（默认，可改）

- **④ capabilities 加载逻辑** → 并入领域模块 `agents/`·`skills/`（内聚；`core/graph` 调它）。
- **⑤ permissions / approvals / audit_agent** → 归 `security/`（授权 / 护栏层）。

## 6. 分期计划（每期独立可验 / 可回滚）

| 期 | 内容 | 验证 |
|---|---|---|
| **P1** | 纯 Python 内部搬迁（**不碰 nexus**）：建 `app/`·`core/`·`security/`·领域模块 → 按 §3 搬文件 + 全量改 import | `uvx ruff`(F401/F821 兜底) + 容器 import 烟测 |
| **P2** | 端口 nexus 逻辑进来：读侧 CRUD + workspace 监听/frontmatter + podman → Python；schema 只认 `db.py` | 起 harness 单栈，管理 API 读写通 |
| **P3** | 前端归一：`web/src/shared/lib/api.ts` 删 nexus base，所有请求走 :8765 | 各 features 页端到端复验 |
| **P4** | 拆除 nexus：删 `nexus-svc/` + `infra/nexus_client.py`；`dev-up.sh`/部署去 nexus 段；config `[nexus]` 节清理；CLAUDE.md / 记忆同步 | `./dev-up.sh` 只剩 harness+postgres+web，全栈跑通 |

## 7. 验证方式

- **每期后**：`uvx ruff check <改动文件>` + 容器 import 烟测（`podman run --rm -e ANTHROPIC_API_KEY=dummy vanta-harness python -c "import harness.app..."`——dummy key 跨过 `chat.py` import 期的 `Settings()` 校验）。
- **P2/P3 后**：`./dev-up.sh` 起栈，管理页(agents/skills/kb/containers)点一遍。

## 8. 施工提示

- P1 的核心风险是**大量 import 路径变动**——靠「移动 + 批量改 import」，逐目录 ruff 兜底。
- 不改运行行为：P1 是纯搬迁，任何逻辑变更留到 P2+。
- 每期一个（或数个）commit，别混期。
