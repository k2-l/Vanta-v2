# Vanta Desktop GUI 实施 Plan

状态：**Approved / v1.0**

对应设计基线：[Tauri Desktop GUI 定稿规范](./tauri-desktop-gui-spec.md)

## 1. 范围与原则

本 Plan 将现有 `desktop/` 从功能骨架推进为定稿 GUI。实现继续遵守瘦客户端边界：

- React WebView 负责展示、输入和短生命周期交互状态。
- Rust Core 负责连接、凭据、远程请求、流式桥接、路径与系统权限。
- 后端是 Session、Run、Approval、Artifact 和 Capability 的业务真值来源。
- 桌面端不复用 Web 页面样式，只复用契约、接口语义和必要的领域类型。
- 未得到后端 capability 声明的功能必须禁用并说明原因。

## 2. 当前基线

### 已完成

- Tauri 2 + React + TypeScript 工程地基。
- Hash 路由与六个一级模块入口。
- 连接配置、登录、钥匙串存储、严格 CSP 和 IPC allowlist。
- 统一错误模型与基础诊断脱敏。
- 会话列表、历史消息、新建会话和流式 Markdown 最小闭环。
- 后端 SSE → Tauri Channel 桥接与停止当前流。
- 浏览器 mock，可在无 Tauri Host 时独立走查。

### 尚未完成

- 定稿版桌面 Shell 与通用组件。
- 对话步骤、工具事件、用量和运行详情投影。
- Runs / Approvals / Artifacts / Capabilities 的真实数据页面。
- 设置模块的完整桌面体验。
- 端到端测试、可访问性检查和发布流水线。

## 3. 交付阶段

### G1.5 — 设计系统与桌面 Shell

目标：先建立所有页面共享的稳定外壳。

- 扩展颜色、排版、间距、层级、动效和响应式 token。
- 实现标题栏、58 px 全局导航、上下文侧栏、主工作区和可关闭详情面板。
- 建立模块级布局状态：侧栏筛选、最近选择、详情开关和窗口断点。
- 补齐通用状态组件与键盘焦点样式。
- 为六个模块提供与定稿一致的静态数据骨架。

完成条件：

- 六个模块可切换，结构与 GUI 规范一致。
- 1280 × 720、1100 × 680、960 × 640 三档截图验收通过。
- 深浅主题、键盘导航和减少动态效果可走查。

### G2 — 对话与运行闭环

目标：让一次对话的执行过程可以实时观察、停止并恢复。

- 将后端事件归一化为消息、阶段、工具调用、用量和产物引用 view model。
- 对话页实现步骤卡、工具事件、错误恢复和输入器状态机。
- Runs 页实现列表、状态/时间筛选、详情时间线和 Agent 层级。
- 接入 `run_subscribe`、sequence 去重、断线重连和 capability 降级。
- 支持从对话跳转到运行，从运行回到来源会话。

完成条件：

- 流式文本顺序稳定；停止、断线和重连不会产生重复消息。
- 运行状态与后端 snapshot/replay 结果一致。
- 不支持 snapshot/replay 的服务器显示明确降级状态。

### G3 — 审批与产物闭环

目标：完成 Human-in-the-loop 与任务输出管理。

- Approvals 页接入全局待处理队列、详情、批准、拒绝和过期状态。
- 审批操作增加 request id，防止重复提交。
- Artifacts 页接入列表、来源追踪、受控预览与安全导出。
- 建立 Chat / Run / Approval / Artifact 间的双向跳转。
- 文件导出只通过 Rust Core 和系统路径选择器完成。

完成条件：

- 审批卡完整展示风险、范围和影响；结果可追溯。
- 重连后待审批项不丢失、不重复处理。
- 导出能力不可用时不会显示可执行假入口。

### G4 — 能力与设置

目标：让用户看懂当前客户端能够做什么，以及能力来自哪里。

- Capabilities 页接入 Agent、Skill、MCP、Knowledge 和执行环境目录。
- 展示来源、可用状态、依赖、同步时间和失败原因。
- Settings 页完成连接、外观、通知、快捷键、更新、诊断和关于。
- 补齐远程 HTTPS 校验、连接测试、版本兼容提示和安全诊断导出。

完成条件：

- 页面只展示后端声明或本机确实可用的能力。
- 凭据不进入 WebView、日志、剪贴板或诊断包。
- 连接切换后所有查询、订阅和缓存按 connection id 隔离。

### G5 — 质量与发布

目标：达到可持续交付的桌面产品质量。

- 单元测试覆盖事件归一化、状态机、权限与脱敏边界。
- 组件测试覆盖发送、停止、审批、导出和连接切换。
- Tauri 端到端测试覆盖登录、聊天、重启恢复和断线恢复。
- 执行可访问性、性能、内存与长会话稳定性检查。
- 配置签名、自动更新、平台安装包和发布说明。

完成条件：

- TypeScript build、Rust test、Python 相关回归与端到端测试全部通过。
- macOS 首发包可安装、可升级、可回滚；Windows/Linux 进入兼容验证矩阵。
- 发布清单中的安全、隐私、诊断和恢复项全部签字确认。

## 4. 推荐代码结构

```text
desktop/src/
  app/shell/             # 标题栏、全局导航、上下文侧栏、详情面板
  components/desktop/    # 定稿通用组件
  features/chat/         # 对话状态机与事件投影
  features/runs/         # 运行查询、订阅与视图模型
  features/approvals/    # 审批队列与操作
  features/artifacts/    # 产物预览与导出
  features/capabilities/ # 能力目录
  features/settings/     # 客户端设置
  contracts/             # IPC / REST / event 契约
  ipc/                   # Tauri invoke、Channel 与 browser mock
  styles/                # tokens、基础样式、动效
```

页面文件只负责编排布局；数据获取和业务状态进入对应 `features/`，跨模块选择状态进入小型 Zustand store，服务端状态继续由 TanStack Query 管理。

## 5. 契约优先级

实施前按以下顺序冻结或补齐契约：

1. Chat stream：`session`、`text_delta`、阶段、工具、用量、错误、关闭原因。
2. Run：summary、snapshot、sequence event、cancel capability。
3. Approval：request、scope、risk、status、decision、expiry。
4. Artifact：metadata、source refs、preview capability、export capability。
5. Capability：kind、source、availability、dependency、last_sync。

契约新增需同步更新：Python schema、Rust DTO/command、TypeScript 类型和 browser mock。字段兼容使用显式 alias，不在 UI 层猜测多种格式。

## 6. 测试与评审节奏

每个阶段按同一顺序交付：

1. 契约与 mock。
2. 静态 GUI 与全部页面状态。
3. Rust Core 接入。
4. 真实后端联调。
5. build/test、窗口截图与安全边界复核。

每个阶段使用独立提交，提交信息包含阶段号。视觉变更必须回写 GUI 定稿规范；协议变更必须同时更新四层契约。

## 7. 非目标

- 不在桌面端复制后端 Agent 编排逻辑。
- 不让 WebView 直接请求任意后端或持有 JWT。
- 不在首版实现 Web 管理后台的全部配置功能。
- 不为尚未声明的服务器能力制作可操作的假界面。
- 不在本 Plan 中引入移动端布局或多窗口工作区。
