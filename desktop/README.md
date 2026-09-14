# Vanta Desktop（Tauri 瘦客户端）

按 [`docs/tauri-thin-client-plan.md`](../docs/tauri-thin-client-plan.md) 搭建的桌面客户端。
当前进度：**G0 协议与工程地基**（骨架）。

## 边界（方案 §5.1）

- **React WebView**：只展示、输入、短生命周期 UI 状态；只调用 allowlist 中的 Tauri command。
- **Rust Core**：持有连接与凭据、发起所有远程 HTTP、归一化错误、（后续）转发事件。
- WebView 不保存 JWT/口令，不直连任意后端地址。

## 目录

```
src/
  contracts/   协议契约：errors / connection / events / ipc（前后端同构）
  ipc/         类型化 invoke（Tauri）+ 浏览器 mock（无 host 时）
  stores/      Zustand：connection（全局连接状态）/ ui
  features/    connection（连接管理 / 登录 / 状态徽标）
  pages/       chat / runs / approvals / artifacts / capabilities / settings
  components/  基础组件层
  styles/      设计 tokens（深浅色）
src-tauri/
  src/
    error.rs            ClientError（§8.3）
    connections/        profile 存储 + URL 标准化（§9.1）
    credentials/        钥匙串凭据保管（§14.2）
    backend_gateway/    REST + ApiOperation 枚举 + 错误归一化（§8）
    diagnostics/        脱敏
    commands/           IPC allowlist
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

首次构建前生成图标（`src-tauri/icons/` 目前为空）：

```bash
npm run tauri icon path/to/logo.png
```

然后：

```bash
npm run tauri:dev     # 开发
npm run tauri:build   # 打包
```

## G0 完成标准

- [x] 独立 `desktop/` 工程，前端 `tsc -b` + `vite build` 通过
- [x] 契约冻结：ClientError / ConnectionProfile / 事件信封 / IPC allowlist
- [x] Rust command / 错误模型 / connection profile / 凭据保管（源码就绪）
- [x] UI tokens、hash 路由、六区导航、基础组件
- [ ] 连真实后端登录取版本（需装 Rust 工具链后 `tauri:dev` 验证）
- [ ] 后端补 `/health` capability 协商与 run 标识（前端已按可选字段容错）

## 待办（进入 G1 前）

- 装 Rust 工具链，`cargo build` 校验 Core（本机当前无 cargo）
- 生成应用图标
- 补 eslint 配置（`npm run lint` 脚本已留位）
- 后端 `/health` 增加 `capabilities` / `api_version` 字段
