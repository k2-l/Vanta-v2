# Vanta Desktop（Tauri 瘦客户端）

Vanta 的 Tauri 2 桌面瘦客户端。当前进度：**G3 审批与产物闭环已完成，正在进入真实后端联调**。

设计与施工基线：

- [GUI 定稿规范](../docs/tauri-desktop-gui-spec.md)
- [GUI 实施 Plan](../docs/tauri-desktop-implementation-plan.md)

## 边界（方案 §5.1）

- **React WebView**：只展示、输入、短生命周期 UI 状态；只调用 allowlist 中的 Tauri command。
- **Rust Core**：持有连接与凭据、发起所有远程 HTTP、归一化错误、（后续）转发事件。
- WebView 不保存 JWT/口令，不直连任意后端地址。

## 目录

```
src/
  app/shell/           标题栏 / 全局导航轨 / 应用壳（四层结构骨架）
  components/desktop/   定稿通用组件：ModuleLayout / ContextRail / DetailPanel /
                        ResourceList / RunTimeline / ApprovalCard / ArtifactPreview /
                        DesktopComposer / StatusDot·StatusBadge / states（空·错误·离线…）
  contracts/   协议契约：errors / connection / stream（流事件）/ events / ipc
  ipc/         类型化 invoke（Tauri）+ chat / run 流封装 + 浏览器 mock（无 host 时）
  stores/      Zustand：connection（全局连接状态）/ ui（主题·模块级布局状态）
  hooks/       useTheme（主题应用）/ useBreakpoint（窗口断点）/ useHotkeys（快捷键）
  features/    connection · chat（步骤卡）· runs（事件归一化 projection /
               phases 快照 / RunDetail）· approvals / artifacts / capabilities
  lib/         cn（类名合并）/ format（时间·时长·字节·token）
  pages/       chat / runs / approvals / artifacts / capabilities / settings
  styles/      设计 tokens（深浅色·四级 surface·排版·动效）+ 全局样式
src-tauri/
  src/
    error.rs            ClientError（§8.3）
    connections/        profile 存储 + URL 标准化（§9.1）
    credentials/        钥匙串凭据保管（§14.2）
    backend_gateway/    REST + ApiOperation 枚举 + 错误归一化
    diagnostics/        脱敏
    commands/           IPC allowlist + SSE → Channel 流式桥
  capabilities/         最小 capability（§14.1）
  tauri.conf.json       严格 CSP、窗口配置
```

## 运行

### 前端（浏览器，mock IPC —— 无需 Rust）

```bash
cd desktop
npm install
npm run dev        # http://localhost:5180
```

无 Tauri host 时，IPC 走内存 mock（连接/凭据为假数据），可独立走查全部 UI。

### 桌面（需 Rust 工具链）

Rust 未安装时先装：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# Linux 还需 WebKitGTK 等系统依赖，见 https://v2.tauri.app/start/prerequisites/
```

应用图标已生成。运行：

```bash
npm run tauri:dev     # 开发
npm run tauri:build:debug  # 生成含最新前端资源的 target/debug/vanta-desktop
npm run tauri:build   # 打包
```

Apple Silicon（M1～M5）统一使用 Rust 目标 `aarch64-apple-darwin`。在 M5 Mac 上生成
原生 ARM64 `.app`（不会通过 Rosetta 运行）：

```bash
npm run tauri:build:mac-arm64:debug  # 本机联调包，ad-hoc 签名
npm run tauri:build:mac-arm64        # ARM64 release 包，ad-hoc 签名
```

产物分别位于
`target/aarch64-apple-darwin/debug/bundle/macos/Vanta.app` 与
`target/aarch64-apple-darwin/release/bundle/macos/Vanta.app`。正式分发时不要使用 ad-hoc
签名脚本，应配置 Apple Developer ID 证书和 notarization 凭据后执行发行构建。

不要把裸 `cargo build` 作为桌面 GUI 的常规构建入口：它不会执行 Tauri 配置中的
`beforeBuildCommand`，可能把旧的或缺失的 `dist/` 嵌入 `target/debug/vanta-desktop`，表现为
窗口能够启动但内容空白。开发使用 `tauri:dev`；需要独立 debug 程序时使用
`tauri:build:debug`。

## G0 完成标准

- [x] 独立 `desktop/` 工程，前端 `tsc -b` + `vite build` 通过
- [x] 契约冻结：ClientError / ConnectionProfile / 事件信封 / IPC allowlist
- [x] Rust command / 错误模型 / connection profile / 凭据保管（源码就绪）
- [x] UI tokens、hash 路由、六区导航、基础组件
- [x] Rust Core 编译与单元测试通过
- [x] 后端 `/health` 提供 `capabilities` / `api_version`
- [x] 连真实后端完成端到端登录、流式聊天与主动上下文压缩验证

## G1 当前能力

- 会话列表与消息历史
- 会话重命名与带二次确认的删除（消息、阶段与运行记录随会话级联删除）
- 新建会话、发送消息、流式 Markdown 回复
- 输入器下方可主动压缩已有会话：先生成可编辑的结构化摘要和 Token 对比，确认后提交检查点；原始消息不删除
- Rust Core 持有后端 URL、访问/刷新令牌；自动轮换短期令牌并通过 Tauri Channel 有序转发 SSE
- 服务端可撤销登录会话；设置页展示两级到期时间，支持手动刷新和退出登录
- 停止当前流、浏览器 mock 独立走查

## G1.5 新增（设计系统与桌面 Shell）

- 扩展设计 tokens：四级 surface、品牌 `#6657EE`、语义色、排版/圆角/动效、布局尺寸。
- 四层外壳：标题栏（工作区身份 + 活动连接 + 拖动区）、58px 全局导航轨（六模块 + 未读角标）、
  上下文侧栏、主工作区、可关闭详情面板。
- 模块级布局状态：详情开关、侧栏筛选、最近选择、窗口断点（<1100 收详情 / <900 压缩侧栏）。
- 主题：深色默认 + 完整浅色 + 跟随系统（持久化，无 FOUC）。
- 快捷键：⌘/Ctrl+K 聚焦搜索、⌘/Ctrl+N 新建对话、Esc 关闭详情；全局焦点环。
- 六模块与定稿一致的静态骨架：Runs（列表 + Agent 树 + 时间线 + 预算）、
  Approvals（风险/范围/影响卡 + 追溯）、Artifacts（列表 + 受控预览 + 能力门控导出）、
  Capabilities（按来源分组 + 四种可用性）、Settings（连接/外观/通知/快捷键/更新/诊断/关于）。
- 对话页重构进新壳，保留原有登录与流式闭环；用户消息弱强调、Agent 开放布局。

## G2 新增（事件归一化 + 真实 Runs / 对话详情）

后端无一等公民「run」：执行单元是 **session + phase 树**，故 **run ≈ session**、
**invocation/Agent 树 ≈ phase 树**（`GET /sessions/{id}/phases` 为快照）。

- 契约：`contracts/stream.ts` 按 `harness/core/foundation/events.py` 逐一对齐的判别联合
  （text_delta / tool_* / worker_* / usage / phase / task_log / done）+ `snapshot` / `stream.closed`。
- 归一化：`features/runs/projection.ts` 纯 reducer `applyPacket` 把流事件折叠成
  RunProjection（可见回答、phase 树、工具事件、独立 token 用量、状态），phases 快照
  幂等对账（按 phase id 去重、断线重新拉快照而非按 seq 重放）。
- 对话：流式期间内联步骤卡（阶段 + 工具）、用量、错误恢复（重试）与输入器状态机；
  运行详情面板实时展示 Agent 树 / 时间线 / 用量。
- 运行页：`GET /runs` 一次聚合状态、阶段数与耗时，避免逐会话拉 phases 的 N+1；
  支持状态/时间筛选，详情由阶段快照与结构化运行历史共同重建。
- 历史遥测：后端持久化经过凭据脱敏的 phase / tool / worker / task_log / usage / done，
  `GET /sessions/{id}/events` 支持 seq 游标；升级后产生的旧运行可恢复工具结果、Token 与耗时。
- `run_subscribe`（Rust）：无 WS 依赖，改为轮询 `/sessions/{id}/phases` 作为带自增 seq 的
  `snapshot` 包推送，终态或客户端停止即结束；Runs 详情已接入该订阅，页面卸载时自动停止。
- 历史对话的运行详情会从 phases 快照恢复；空快照不再被误判为完成，失败快照保持失败终态。
- 投影层覆盖公开文本、工具结果、用量、乱序 phase 树和 snapshot seq 去重测试。
- 能力协商如实：后端 `run_snapshot=True`、`run_history=True`；`event_replay=False`
  （正文 delta 仍不做完整重放，详情面板显式降级提示），`run_cancel=False`。
- 对话 ↔ 运行双向跳转（共享 session_id）。

## G3 新增（审批与产物闭环）

- 审批（HITL）：后端补 `GET /chat/approvals` 暴露进程内待处理队列（call_id / tool_name /
  message / session_id / requested_at / expires_at）；桌面轮询该队列，决策走既有
  `POST /chat/approvals/{call_id}`，以 call_id 为幂等键防重复提交。
- 审批结果与超时项先写 `approval_history` 持久投影，再写哈希链审计账本；账本临时失败时
  保留 outbox 状态，历史查询会按 `decision_id` 自动补账。持久化失败不唤醒待执行工具。
- 审批页：待处理、已批准、已拒绝和持久化已过期记录；后端提供风险/来源/对象/范围/影响，
  详情展示审计证据并跳转来源会话；多卡按 call_id 独立提交。
- 产物：`GET /v1/artifacts` / `{id}` 返回真实 UTF-8 大小、更新时间、媒体类型及明确的
  `source_session_id` / `source_run_id`；支持类型/来源筛选和 Chat ↔ Run ↔ Artifact 跳转。
- 受控预览：Markdown、纯文本、JSON/代码及白名单 raster data URL；未知类型只显示元数据；
  **secret 类只显示元数据、不回明文且禁止导出**。
- 安全导出：后端声明 `artifact_export=True`；Rust Core 重新读取权威产物，拒绝 secret，
  清洗文件名并以不可覆盖的唯一名称写入系统下载目录 `Vanta Exports`，WebView 不能传路径或正文。
- 契约四层同步：Python schema/route、Rust gateway/command、TS contract/UI、浏览器 mock。

## 联调前收口（模块生命周期与后端清理）

- 六个 GUI 模块统一通过单一导航入口切换；模块首次访问后保持挂载，返回时保留草稿、筛选、
  最近选择和滚动位置，对话流不会因为查看 Runs、审批或产物而中断。
- 切换服务器连接时才整体销毁模块工作区，并取消旧连接查询、清理资源选择；快速切换时，迟到的
  激活或登录结果不会覆盖当前连接。
- Rust 激活连接时严格校验后端 API v1，并调用 `/auth/me` 验证钥匙串令牌；401 会清理失效令牌，
  其它握手失败不会伪装成已连接。
- 已移除后端旧工具别名、旧审批捷径、废弃上下文配置、未使用图导出、MCP 兼容门面及知识库双写；
  清理范围和联调门槛见 [后端清理审计](../docs/backend-cleanup-audit.md)。

## 下一步

- 重启真实后端完成 `approval_history` 与 artifact 新字段迁移，并做审批、补偿和导出真机联调。
- 为升级前旧 artifact 回填来源；二进制图片/附件需要独立存储契约后再接入，不把任意字节塞进 WebView。
- run_subscribe / approvals 可在后续升级为 WS 实时（`/ws/chat/{id}`）替代轮询。
- 补 ESLint、组件/Tauri E2E 与平台安装包验收。

## 当前 HTTP 联调

开发期允许本机及远程 HTTP，当前后端配置的证书/私钥项已注释。
重启 `uv run harness-api` 后，桌面端新建连接 `http://10.1.1.2:8765`，测试、保存并激活；
HTTP 不需要 CA 证书。已有 HTTPS 连接不会自动改写。

Windows 客户端需重新编译。当前 Linux 交叉编译环境命令（由用户执行）：

```bash
cd /root/Vanta-v2/desktop
source ~/.cargo/env
export PATH="/root/.local/bin:/usr/lib/llvm-19/bin:$PATH"
export XWIN_ARCH=x86_64
export XWIN_CACHE_DIR=/tmp/vanta-windows-xwin
export CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS='-C target-feature=+crt-static'
CARGO_BUILD_JOBS=2 npm run tauri -- build --runner cargo-xwin --target x86_64-pc-windows-msvc --no-bundle -- --locked
```

程序输出：`desktop/target/x86_64-pc-windows-msvc/release/vanta-desktop.exe`。
需要运行 Rust 回归时，在加载上述 Rust 环境后执行 `cargo test --locked --offline`。
上线前配置正确的服务器证书、修复系统信任库接入并恢复生产 HTTPS 策略。
