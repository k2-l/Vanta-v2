# Vanta Desktop（Tauri 瘦客户端）

Vanta 的 Tauri 2 桌面瘦客户端。当前进度：**G2 事件归一化 + 真实 Runs / 对话详情**。

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
- [ ] 连真实后端完成端到端登录与聊天验证

## G1 当前能力

- 会话列表与消息历史
- 新建会话、发送消息、流式 Markdown 回复
- Rust Core 持有后端 URL/JWT，通过 Tauri Channel 有序转发 SSE
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
- 运行页：列表 = sessions（复用缓存）+ 每个 run 的 phases 快照派生状态/步骤；
  状态/时间筛选；详情由快照重建（Agent 树 / 时间线）。
- `run_subscribe`（Rust）：无 WS 依赖，改为轮询 `/sessions/{id}/phases` 作为带自增 seq 的
  `snapshot` 包推送，终态或客户端停止即结束；Runs 详情已接入该订阅，页面卸载时自动停止。
- 历史对话的运行详情会从 phases 快照恢复；空快照不再被误判为完成，失败快照保持失败终态。
- 投影层覆盖公开文本、工具结果、用量、乱序 phase 树和 snapshot seq 去重测试。
- 能力协商如实：后端 `run_snapshot=True`（快照可用），`event_replay=False`（不支持按序重放，
  详情面板显式降级提示），`run_cancel=False`。
- 对话 ↔ 运行双向跳转（共享 session_id）。

## G3 新增（审批与产物闭环）

- 审批（HITL）：后端补 `GET /chat/approvals` 暴露进程内待处理队列（call_id / tool_name /
  message / session_id / requested_at / expires_at）；桌面轮询该队列，决策走既有
  `POST /chat/approvals/{call_id}`，以 call_id 为幂等键防重复提交。
- 审批页：待处理（服务端权威）+ 本次会话已批准/已拒绝记录；风险按工具名启发式分级并如实标注；
  详情可追溯并跳转来源会话；导航轨未读角标改为实时待处理数量。
- 产物：接入只读 `GET /v1/artifacts`（看板 artifact）；列表含来源/类型/敏感级/严重度；
  受控预览（evidence 按 Markdown）；**secret 类只显示元数据、不回明文**（后端不下发正文）。
- 导出能力门控：`artifact_export=False` 时导出入口禁用并说明原因，不显示可操作假入口。
- 契约四层同步：Rust gateway（`approvals.decide` / `artifacts.list`）、TS ApiOperation、
  `contracts/resources.ts`（Approval / Artifact 线型）、浏览器 mock。

## 下一步

- G4：能力与设置真实接入（Agent/Skill/MCP/Knowledge/执行环境目录、连接诊断）。
- 审批/产物富化：审批请求携带显式风险/范围/影响；artifact 导出走 Rust Core 安全路径选择。
- run_subscribe / approvals 升级为 WS 实时（`/ws/chat/{id}`）替代轮询。
- 补 ESLint 配置与前端交互测试。

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
