# Vanta Desktop GUI 实施 Plan

状态：**Approved / v1.0**。设计基线见 [GUI 定稿规范](./tauri-desktop-gui-spec.md)；本文只记录实施范围、当前进度和验收缺口，不修改设计要求。

进度快照：**2026-09-16**，依据当前工作区及物理机反馈。代码落地不等于验收通过。

## 1. 实施边界

- React WebView 负责界面与短生命周期交互；Rust Core 负责连接、钥匙串凭据、远程请求、流式桥接和系统路径权限。Session、Run、Approval、Artifact、Capability 的业务真值在后端。
- 桌面端不复制 Web 页面或后端 Agent 编排；WebView 不持有 JWT，也不能请求任意 URL。未获后端 capability 声明的操作必须禁用并说明原因。
- 页面编排留在 `pages/`，数据与状态进入 `features/`；已访问模块保留挂载，跨模块选择/详情通过统一导航入口写入 Zustand，服务端查询使用 TanStack Query。协议变更同步 Python schema、Rust DTO/command、TypeScript 契约与 browser mock；工具和 IPC 入参不保留隐式旧名。

## 2. 当前基线

开发期按已确认决策允许远程 HTTP。后端现用 `http://10.1.1.2:8765`，客户端在 HTTP 下忽略旧 CA 路径；已有 HTTPS profile 不自动迁移。HTTPS 能力保留，上线前须收口证书用途、信任库和生产连接策略。

物理机浏览器访问 `/health` 正常；客户端 HTTP 测试连接和基本回答曾验证。先前对话 401 是后端上游模型密钥无效，配置修正后可回答。`run.log` 又暴露后端流收尾缺陷：未配置 Qdrant 时自动记忆写入抛异常，导致 SSE 的 ASGI traceback；本地已改为未配置时跳过自动记忆、配置后故障也不阻断回答落库。Agent/Skill 目录与工具工作目录曾分别指向旧 `/root/Vanta/workspace` 和缺失的 `suite_dir`，本地已统一并在启动时创建工作区。这些修复尚未在实际后端进程重启后复验。回答详情的 `api_request` `sessionId` / `session_id` 映射已修复；**新 Windows 包与测试尚未复验**。

| 阶段 | 已落地 | 待验收 / 待实现 |
|---|---|---|
| G0 / G1 地基与聊天 | Tauri 2、六模块入口、受控 IPC、SSE→Channel、会话与流式回答；访问/刷新令牌只存钥匙串，短令牌自动轮换、服务端会话可撤销；会话重命名/删除已进入 GUI；物理机已验证连接和基本回答 | 新认证会话的真实后端迁移与端到端复验；长会话、停止和断线验证 |
| G1.5 Shell | 设计 token、导航/侧栏/详情、主题、快捷键、响应式与通用状态组件 | 1280×720、1100×680、960×640 截图；键盘/主题/减少动态效果走查与滚动位置恢复 |
| G2 对话与运行 | 文本/阶段/工具/用量投影；主动上下文压缩通过 preview→可编辑确认→commit 写入检查点，原文保留；Runs 单请求聚合列表，以 phases + 脱敏结构化事件历史构建树、工具、Token、耗时和时间线，支持筛选、快照订阅、重连、Chat↔Runs 跳转及关联产物入口 | 停止/断线/重连真机验证；正文 delta 重放与运行取消未提供；升级前旧运行无遥测历史 |
| G3 审批与产物 | 真实审批队列与四态历史；风险/对象/范围/影响；decision_id + 哈希链；持久审批 outbox 与自动补账；多卡独立提交，持久化失败不放行。产物带真实大小/更新时间/媒体类型及 session/run 来源，支持类型/来源筛选、Markdown/文本/JSON/白名单图片预览、三模块互跳；Rust Core 重新拉取权威正文并以安全文件名无覆盖导出，secret 不下发也不导出 | 重启真实后端验证数据库迁移、审批/补账与真实 Tauri 导出；升级前旧产物需回填来源；二进制附件尚无独立存储契约 |
| G4 能力与设置 | 五类真实能力目录及单来源降级；七类设置入口；模块访问后保活；连接切换先取消查询并重置资源上下文；激活时校验 API v1 与 `/auth/me`；设置页展示访问/登录会话到期时间并支持刷新/退出；更新未配置提示、Rust 诊断导出 | 能力可用性/位置/同步时间、真实连接切换与诊断脱敏验收；通知、签名更新、版本兼容提示 |
| G5 质量与发布 | 投影、流解析、脱敏、IPC、后端协议与关键状态单元回归 | 组件/Tauri E2E、可访问性、性能、平台安装/更新/回滚及发布签字 |

以下是**不能按“已完成”宣传的能力边界**：

- `run ≈ session`；`run_subscribe` 约每 1.5 秒轮询 phases，snapshot sequence 是客户端序号。后端另以全局单调 seq 持久化脱敏后的结构化运行事件，声明 `run_snapshot=true`、`run_history=true`；正文 delta 不入事件历史，故仍如实声明 `event_replay=false`。`run_cancel=false`；停止按钮只停止当前对话流。
- 审批历史以 `approval_history` 持久投影承接结果/过期状态，以哈希链 `entry_hash` 作为审计证据；账本失败会保留 `audit_recorded=false` 并在历史查询时按 decision_id 补账。前端只在内存保留刚提交的乐观记录，服务端历史优先；旧版敏感 localStorage 在启动时清理。待真实后端验证迁移、超时、并发决策和补账链路。
- Artifacts 是 `/v1/artifacts` 的只读看板资源；新产物显式关联 session/run 并返回后端计算的大小、更新时间和媒体类型。导出由 Rust Core 写入系统下载目录，WebView 无法指定路径或正文；secret 拒绝导出。升级前旧产物可能没有来源，二进制附件仍需独立存储契约。
- 能力目录来自 `/v1/agents`、`/v1/skills`、`/v1/mcp/servers`、`/v1/knowledge`、`/v1/containers`。Agent/Skill/Knowledge 的“可用”尚未验证依赖就绪；容器状态可能退回数据库记录，MCP 位置目前固定“本机”，“同步时间”只是客户端查询时间。后端未配置 Qdrant 时自动记忆与记忆召回不可用，但基本对话不依赖它们；工作区目录统一修复尚待实际进程复验。
- 诊断导出不读取钥匙串令牌，但连接名称/URL 可含用户自填敏感内容，`redact` 只匹配有限标记。连接切换会清选择和连接查询、重挂载页面并触发流订阅清理；快速切换的迟到回调已有单元回归，真实 Tauri Host 下仍需验证。

证据入口：[Shell](../desktop/src/app/shell/)、[运行投影](../desktop/src/features/runs/projection.ts)、[Rust 流桥接](../desktop/src-tauri/src/commands/stream.rs)、[审批记录](../desktop/src/features/approvals/decisions.ts)、[审批门/风险派生](../harness/security/approvals.py)、[审批决策/历史路由](../harness/routes/chat.py)、[产物页](../desktop/src/pages/artifacts/index.tsx)、[能力目录](../desktop/src/features/capabilities/useCapabilities.ts)、[系统命令](../desktop/src-tauri/src/commands/system.rs)。

验证记录：前端 `npm run build` 与 `npm test` 通过（14 个用例，六个业务模块按需分包）；Rust `cargo test` 通过（9 个用例）；后端 54 个 unittest 与全仓 Ruff 通过。新增覆盖访问/刷新令牌类型隔离、撤销会话、会话标题校验与桌面 API 契约。浏览器 mock 已走查登录状态卡、令牌刷新、会话重命名和删除确认面板；真实后端迁移与认证联调仍待下一轮真机走查。`git diff --check` 通过。本机 Rust 工具链未安装 rustfmt/clippy，`npm run lint` 因未安装 `eslint` 无法执行；真实数据库迁移、审批并发、Tauri Host 写盘与 Windows 包仍待验收。后端删除清单与保留边界见 [后端清理审计](./backend-cleanup-audit.md)。

## 3. 下一步

1. 按 [后端清理与联调门禁](./backend-cleanup-audit.md) 启动真实后端，先验证 API v1、登录/失效令牌和无 Qdrant 的基本对话，再验证流式回答期间切换 Runs/Artifacts 不丢流、停止/断线/重连与连接快速切换。
2. G3 代码闭环已补齐；重启后端执行新表/新列迁移，真机验证审批超时、并发决策、审计补账和 Rust 下载目录导出，并决定旧产物来源回填策略与二进制附件存储契约。
3. 校正 G4 能力的依赖就绪、运行位置和后端 last_sync；验收诊断脱敏与连接隔离，接入通知、签名更新和版本兼容提示。
4. 补 G5 组件/Tauri E2E；完成可访问性、长会话和性能检查，以及 macOS 首发安装/升级/回滚、Windows/Linux 兼容矩阵和发布清单签字。

## 4. 交付规则

契约优先级：Chat stream → Run snapshot/event/cancel → Approval risk/decision/expiry → Artifact source/preview/export → Capability availability/dependency/last_sync。每阶段按“契约与 mock → GUI 状态 → Rust 接入 → 真实后端联调 → build/test、截图和安全边界复核”交付；视觉变更回写 GUI 规范，协议变更更新四层契约。

首版不实现 Web 管理后台全部配置、移动端布局或多窗口工作区；未声明的能力不做可操作的假入口。
