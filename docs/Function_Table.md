# Harness 后端功能清单

`harness/` 是一个以 **LangGraph 为核心的多 Agent 安全测试 / 代码审计智能体后端**（FastAPI + PostgreSQL + Qdrant + Podman）。下面按子系统分类列出全部功能。

## 一、HTTP / WebSocket API 层（`app/` + `routes/`）

| 功能名称 | 作用 |
|---|---|
| 单用户鉴权 `POST /auth/login`·`GET /auth/me` | 密码校验（常时比较）签发 HS256 JWT，7 天有效；按 IP 令牌桶登录限流；`require_auth` 保护所有其他路由 |
| 健康检查 `GET /health` | 返回状态、版本、worker 模型（公开） |
| 运行指标 `GET /metrics` | 进程级指标快照（LLM 调用数、工具调用、缓存命中、注入检测等） |
| 用户 Profile `GET/PUT /profile` | 读写 `data/profile.md` 用户画像，注入到每轮上下文 |
| 流式对话 `POST /chat` | SSE 流式对话主入口；驱动 LangGraph 运行，实时推送文本/工具/阶段事件，落库运行遥测 |
| HITL 审批队列 `GET /chat/approvals`、`POST /chat/approvals/{call_id}`、`/history` | 人机协同审批：列出挂起项、批准/拒绝工具调用、查询持久化决策历史（带哈希链审计证据） |
| 运行时配置 `GET/PATCH /config` | 白名单字段的读写（模型三档、压缩比、token 预算、子 Agent/工具并发上限等），持久化到 config 覆盖层 |
| 会话管理 `/sessions` CRUD | 会话增删改查、改标题、消息列表 |
| 会话主动压缩 `/sessions/{id}/compress/preview`·`commit` | 把历史压成结构化摘要（可编辑后提交），原文保留可回退 |
| 运行详情 `/sessions/{id}/phases`·`/events`、`/runs` | 查询执行阶段树、结构化运行事件流、运行摘要列表（用于重建运行详情） |
| 经验记忆 `/memory/remember·list·search·clear` | 向量长期记忆的写入/列出/语义检索/清空 |
| Token 预算 `GET /budget/{session_id}` | 查询会话 token 预算状态 |
| 技能管理 `/v1/skills/*` | Skill 的 CRUD、Markdown 注册、依赖树、向量重建索引 |
| Agent 管理 `/v1/agents/*` | Agent 的 CRUD、Markdown 注册、provider 归一化 |
| 知识库管理 `/v1/knowledge/*` | 知识条目 CRUD、Markdown 注册、目录扫描导入、Qdrant 重建索引 |
| 容器管理 `/v1/containers/*` | 直连 Podman 的容器创建/启停/删除/exec；Profile/readiness 管理 Agent runtime 自动选择能力 |
| 结果看板 `GET /v1/artifacts` | 操作者视角只读查看跨 engagement 的产物（secret 不回明文） |
| MCP Server 管理 `/v1/mcp/servers/*` | 可视化增删/测试外部 MCP server，二次确认写门槛，env 脱敏（只回 key 名），热挂载/卸载 |
| 实时推送 `WS /ws/chat/{session_id}` | WebSocket 订阅会话 task 状态事件（JWT 校验） |

## 二、Agent 运行时 / 编排引擎（`core/`）

| 功能名称 | 作用 |
|---|---|
| AgentRuntime（LangGraph 引擎） | `preprocess→agent→tools→recovery` 状态图，把 `astream_events` 映射为 Harness SSE 事件 |
| 子 Agent 编排（`subagent/`） | `run_sub_agent` 独立执行子 Agent，支持同轮并行；深度限制、委派循环检测、并发信号量门控 |
| Agent Runtime Resolver | 按 invocation 的能力/网络/工作区需求选择容器，readiness 探测、租约并发控制、失败不回退本机 |
| 上下文构建（L1/L2/L3） | L1 注入 agent/skill 清单，L2 按需加载 SOP/system prompt，L3 渐进披露附带文件 |
| 上下文压缩 / 摘要 | rolling summary 背景注入 + 用户主动结构化压缩（新覆盖旧淘汰过期信息） |
| Token 预算与用量成本 | 会话/每日/主 Agent/子 Agent 预算门控，按模型价格表估算每轮与会话成本 |
| 长期记忆能力 | 回答后自动过滤并写入向量记忆（跳过纯确认句、超长截尾） |
| 会话标题生成 | fire-and-forget 后台按首轮内容生成会话标题 |
| 崩溃续跑 | 启动标记中断轮 + AsyncPostgresSaver checkpointer，图执行可续跑 |
| 并发控制 | per-session 锁（防消息乱序）+ 全局并发信号量（防 DB/API 打爆） |
| 错误恢复 / 终止分类 | recovery 节点重试，识别不可重试终止错误（认证失败、预算耗尽等）并给可读提示 |
| 内部段过滤 | 剥离仅供 Agent 内部使用的标记，保证流式与落盘边界一致 |

## 三、工具系统（`tools/`）

**内置工具（Agent 可调用）：**

| 工具 | 作用 |
|---|---|
| `Bash` | 经 shell 执行命令（工作目录内 / 容器内 / engagement 沙箱内），权限引擎门控 |
| `Read`·`Write`·`Edit` | 工作目录沙箱内的文件读/写/精确替换，禁读敏感文件（.env/密钥等） |
| `Grep`·`Glob` | 工作目录/容器内正则内容检索与文件名匹配（argv 直传免注入） |
| `knowledge` | 知识库语义检索（向量召回+ReRank，SQL 兜底）与取全文 |
| `WebSearch`·`WebFetch` | 联网搜索（DuckDuckGo/Tavily）与抓取网页正文（SSRF 公网校验） |
| `engagement` | 对话式管理授权测试范围（创建/激活/列出/结束） |
| `finding` | 记录/列出/分诊安全发现（严重度、证据、修复、FP） |
| `board` | 多 Agent 共享结果看板产物读写（按 engagement L1 隔离） |
| `report` | 从 findings 生成结构化 Markdown 渗透测试报告 |
| `Agent`·`load_agent`·`Skill`·`tool_search`·`runtime_catalog` | 派发子 Agent、加载定义、检索动态工具，以及查询安全的 Agent runtime 能力目录 |

**工具基础设施：**

| 功能名称 | 作用 |
|---|---|
| 工具注册表 + 动态披露 | 静态/动态工具管理，声明式 CLI 与 MCP 工具按需 `tool_search` 解锁绑定，控制 token 膨胀 |
| 工具来源协调器 | builtin / MCP / plugin 三类来源走统一挂载路径 |
| MCP stdio 客户端 | 接入外部 MCP server 工具，热挂载/卸载、连接测试 |
| Plugin 来源 | 从插件目录动态接入工具 |
| 输出净化器（sanitizer） | 工具输出的 prompt injection 防御层 |
| 执行上下文（exec_context） | 区分 host / 容器 / engagement 沙箱执行环境 |
| 单次工具执行内核（tool_exec） | 统一权限判定 → 审批门 → 脱敏 → 审计的执行管道 |

## 四、安全子系统（`security/`）

| 功能名称 | 作用 |
|---|---|
| 权限引擎 | 纯逻辑判定工具调用 `allow/ask/deny`（deny>ask>allow），复合命令逐段取最严，支持 default/acceptEdits/plan/bypass 模式 |
| HITL 人工审批门 | 阻塞式等待前端人工批准/拒绝的等待原语 |
| 审计 Agent | `ask` 时用 model_low 自动裁决（默认放行、只拦破坏性动作），fail-closed |
| 哈希链审计账本 | append-only 防篡改动作留痕 |
| Engagement / Scope | 授权范围纯逻辑：scope 匹配 + RoE 有效期校验 |
| 网络隔离沙箱 | per-engagement 用 nft 强制出站边界（scope→IP allowlist，默认 DROP，fail-closed 自检） |
| 凭据保险库 | engagement 凭据 Fernet 加密存储，路径独立于 git |
| 输出保险库 | 工具输出加密存储替代明文目录 |
| 凭据脱敏 | 喂 LLM/落盘前把高置信凭据打码为 `[REDACTED:LABEL]` |
| 库目录安全守卫 | 解析路径、硬拒落在 git 配置路径内、按 0700 建目录 |

## 五、基础设施（`infra/`）

| 功能名称 | 作用 |
|---|---|
| PostgreSQL 持久化 | SQLAlchemy 2.x async + asyncpg（会话/消息/发现/产物/审计等） |
| Qdrant 向量存储 | 长期记忆 + 知识/技能 embedding 检索 |
| Podman 封装 | 容器生命周期与 exec 的 CLI 封装 |
| URL 抓取器 | article（通用 HTML）/ github（REST + README）抓取 |
| 指标计数器 | 轻量进程内指标统计 |
| 事件总线 | 会话级内存 pub/sub，供 WebSocket 广播 |
| 配置覆盖层 | 运行时配置持久化到 `config.local.json` |
| Settings | 集中式配置声明与读取 |
| 重试 / 日志 | Anthropic 瞬时错误重试装饰器；structlog 结构化日志 |
| 慢请求中间件 + 启动装配 | 非流式慢请求告警；启动初始化 DB、checkpointer、工具来源、MCP、插件 |
