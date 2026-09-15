# Vanta Desktop GUI 实施 Plan

状态：**Approved / v1.0**。设计基线见 [GUI 定稿规范](./tauri-desktop-gui-spec.md)；本文只记录实施范围、当前进度和验收缺口，不修改设计要求。

进度快照：**2026-09-15**，依据当前工作区（含未提交改动）及物理机反馈。代码落地不等于验收通过。

## 1. 实施边界

- React WebView 负责界面与短生命周期交互；Rust Core 负责连接、钥匙串凭据、远程请求、流式桥接和系统路径权限。Session、Run、Approval、Artifact、Capability 的业务真值在后端。
- 桌面端不复制 Web 页面或后端 Agent 编排；WebView 不持有 JWT，也不能请求任意 URL。未获后端 capability 声明的操作必须禁用并说明原因。
- 页面编排留在 `pages/`，数据与状态进入 `features/`；跨模块选择使用 Zustand，服务端查询使用 TanStack Query。协议变更同步 Python schema、Rust DTO/command、TypeScript 契约与 browser mock，兼容字段使用显式 alias。

## 2. 当前基线

开发期按已确认决策允许远程 HTTP。后端现用 `http://10.1.1.2:8765`，客户端在 HTTP 下忽略旧 CA 路径；已有 HTTPS profile 不自动迁移。HTTPS 能力保留，上线前须收口证书用途、信任库和生产连接策略。

物理机浏览器访问 `/health` 正常；客户端 HTTP 测试连接和基本回答曾验证。先前对话 401 是后端上游模型密钥无效，配置修正后可回答。`run.log` 又暴露后端流收尾缺陷：未配置 Qdrant 时自动记忆写入抛异常，导致 SSE 的 ASGI traceback；本地已改为未配置时跳过自动记忆、配置后故障也不阻断回答落库。Agent/Skill 目录与工具工作目录曾分别指向旧 `/root/Vanta/workspace` 和缺失的 `suite_dir`，本地已统一并在启动时创建工作区。这些修复尚未在实际后端进程重启后复验。回答详情的 `api_request` `sessionId` / `session_id` 映射已修复；**新 Windows 包与测试尚未复验**。

| 阶段 | 已落地 | 待验收 / 待实现 |
|---|---|---|
| G0 / G1 地基与聊天 | Tauri 2、六模块入口、连接/登录/钥匙串、受控 IPC、SSE→Channel、会话与流式回答；物理机已验证连接和基本回答 | 回答详情新包复验；登录、长会话、停止和断线端到端验证 |
| G1.5 Shell | 设计 token、导航/侧栏/详情、主题、快捷键、响应式与通用状态组件 | 1280×720、1100×680、960×640 截图；键盘/主题/减少动态效果走查与滚动位置恢复 |
| G2 对话与运行 | 文本/阶段/工具/用量投影；Runs 单请求聚合列表，以 phases + 脱敏结构化事件历史构建树、工具、Token、耗时和时间线，支持筛选、快照订阅、重连及 Chat↔Runs 跳转 | 停止/断线/重连真机验证；产物关联；正文 delta 重放与运行取消未提供；升级前旧运行无遥测历史 |
| G3 审批与产物 | 真实待审批队列、批准/拒绝、过期分类；后端审批请求携带 risk/target/scope/impact（工具声明或按 category 派生并标注来源），决策以独立 decision_id 标识并写入哈希链审计账本，新增 `GET /chat/approvals/history` 服务端历史，前端合并服务端历史（权威）与本次页面会话内存记录；多卡按 call_id 独立提交，审计写入失败有明确提示；只读产物列表、Markdown 预览、secret 仅元数据 | 后端问题解决后再做审批契约真机联调；过期项持久历史；产物来源关联、多类型预览、安全导出 |
| G4 能力与设置 | 五类真实能力目录及单来源降级；七类设置入口、连接切换清理、更新未配置提示、Rust 诊断导出 | 能力可用性/位置/同步时间、连接隔离与诊断脱敏验收；通知、签名更新、版本兼容提示 |
| G5 质量与发布 | 局部投影、流解析、脱敏和 IPC 单元测试代码 | 组件/E2E、Python 回归、可访问性、性能、平台安装/更新/回滚及发布签字 |

以下是**不能按“已完成”宣传的能力边界**：

- `run ≈ session`；`run_subscribe` 约每 1.5 秒轮询 phases，snapshot sequence 是客户端序号。后端另以全局单调 seq 持久化脱敏后的结构化运行事件，声明 `run_snapshot=true`、`run_history=true`；正文 delta 不入事件历史，故仍如实声明 `event_replay=false`。`run_cancel=false`、`artifact_export=false`；停止按钮只停止当前对话流。
- 审批历史以服务端哈希链审计账本为权威（`GET /chat/approvals/history`，进程重启后仍可查询）；本次页面会话的乐观记录只在内存保留完整请求，旧版 `vanta.approvals.decisions.*` 存储在启动时清理。按 call_id 与服务端历史合并、服务端优先；多卡提交按 call_id 独立跟踪。决策以独立 decision_id 标识，entry_hash 作为审计证据（写入失败时 `audit_recorded=false` 且 entry_hash 为空，决策仍生效，界面明确提示；页面关闭后该未入账记录不再可见）。风险/对象/范围/影响由后端在审批请求中携带（工具 `risk_level` 声明或按 category 派生并标注 `risk_source`）。仍待验收：后端问题解决后的真机联调；过期项随后端队列清理消失后无历史；审计写入失败的持久可追溯性需要后端补偿机制。
- Artifacts 是 `/v1/artifacts` 的只读看板资源，大小由正文估算、时间来自 `created_at`；来源尚未关联到 session/run，导出入口因 capability=false 禁用。
- 能力目录来自 `/v1/agents`、`/v1/skills`、`/v1/mcp/servers`、`/v1/knowledge`、`/v1/containers`。Agent/Skill/Knowledge 的“可用”尚未验证依赖就绪；容器状态可能退回数据库记录，MCP 位置目前固定“本机”，“同步时间”只是客户端查询时间。后端未配置 Qdrant 时自动记忆与记忆召回不可用，但基本对话不依赖它们；工作区目录统一修复尚待实际进程复验。
- 诊断导出不读取钥匙串令牌，但连接名称/URL 可含用户自填敏感内容，`redact` 只匹配有限标记。连接切换会清选择和查询缓存并重挂载页面，但不等于 Rust IPC/订阅全部取消；快速切换与迟到回调尚未验证。

证据入口：[Shell](../desktop/src/app/shell/)、[运行投影](../desktop/src/features/runs/projection.ts)、[Rust 流桥接](../desktop/src-tauri/src/commands/stream.rs)、[审批记录](../desktop/src/features/approvals/decisions.ts)、[审批门/风险派生](../harness/security/approvals.py)、[审批决策/历史路由](../harness/routes/chat.py)、[产物页](../desktop/src/pages/artifacts/index.tsx)、[能力目录](../desktop/src/features/capabilities/useCapabilities.ts)、[系统命令](../desktop/src-tauri/src/commands/system.rs)。

验证记录：前端 `npm run build` 与 `npm test` 通过（5 个用例，主包约 576 kB）；Rust `cargo test --locked --offline` 通过（8 个用例）。后端 42 个 unittest 与本轮 `ruff` 检查通过，新增覆盖运行历史凭据脱敏、phase 按序归档，并覆盖无 Qdrant 的回答落库、向量故障降级、工作区 Shell 执行与越界拒绝；Python 语法编译及 `git diff --check` 通过。`npm run lint` 因工作区未安装 `eslint` 无法执行。审批多卡真实交互、IPC、窗口截图、数据库新表迁移及后端重启后的真实 SSE 请求未运行；真机联调暂不可用。运行 Cargo 前须 `source ~/.cargo/env`；按用户要求，Windows 重新编译由用户执行。

## 3. 下一步

1. 先重启后端并复验无 Qdrant 的基本对话能落库、正常发出 SSE 收尾事件，检查工作区工具默认目录和相对路径；再复验 Windows 回答详情 IPC 修复。真实后端稳定后检查登录、停止、断线/重连及连接快速切换，并完成三档窗口、键盘和主题验收。
2. G3 后端审批风险/范围/影响、decision id 与服务端历史契约已落地；本地补齐了内存乐观记录、旧存储清理、多卡独立提交与审计失败提示。后端问题解决后再真机联调该契约；补过期历史、审计失败持久补偿、产物关联与 Rust 安全导出。
3. 校正 G4 能力的依赖就绪、运行位置和后端 last_sync；验收诊断脱敏与连接隔离，接入通知、签名更新和版本兼容提示。
4. 补 G5 单元/组件/Tauri E2E 与 Python 回归；完成可访问性、长会话和性能检查，以及 macOS 首发安装/升级/回滚、Windows/Linux 兼容矩阵和发布清单签字。

## 4. 交付规则

契约优先级：Chat stream → Run snapshot/event/cancel → Approval risk/decision/expiry → Artifact source/preview/export → Capability availability/dependency/last_sync。每阶段按“契约与 mock → GUI 状态 → Rust 接入 → 真实后端联调 → build/test、截图和安全边界复核”交付；视觉变更回写 GUI 规范，协议变更更新四层契约。

首版不实现 Web 管理后台全部配置、移动端布局或多窗口工作区；未声明的能力不做可操作的假入口。
