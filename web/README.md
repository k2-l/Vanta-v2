# Hermes Web

> Vite + React 18 + TypeScript + Tailwind v4 + shadcn 风格组件。

## 安装与启动

```powershell
cd D:\work\hermes\web

# 装依赖（首次约 1-2 分钟）
npm install

# 复制环境变量
copy .env.example .env

# 起开发服务（默认 http://127.0.0.1:5173）
npm run dev
```

确保后端 API 已启动：

```powershell
cd D:\work\hermes
uv run hermes-api    # http://127.0.0.1:8765
```

CORS 已在 settings.py 配置 `localhost:5173`，开箱即用。

## 项目结构

```
web/
├── package.json / vite.config.ts / tsconfig.json
├── postcss.config.js                Tailwind v4 + autoprefixer
├── index.html
├── .env.example
└── src/
    ├── main.tsx                     入口
    ├── App.tsx                      三栏主布局
    ├── index.css                    Tailwind v4 + design tokens
    ├── lib/
    │   ├── api.ts                   非流式 REST 封装
    │   ├── sse.ts                   /chat SSE 客户端 + 事件类型
    │   └── utils.ts                 cn 类名合并
    ├── store/
    │   └── chat.ts                  zustand 全局状态 + 事件 reducer
    └── components/
        ├── SessionsSidebar.tsx      左侧会话列表
        ├── MessageList.tsx          主聊天区（含 markdown 渲染）
        ├── ChatInput.tsx            输入框（Enter 发送 / Shift+Enter 换行）
        ├── TasksPanel.tsx           右侧任务面板（可点开看子任务详情）
        ├── StatusBar.tsx            底部状态栏（spinner + 用量）
        └── ui/Button.tsx            shadcn 风格按钮
```

## 已实现

- 会话列表：自动加载 / 新建 / 切换 / 删除
- 聊天：Enter 发送，流式接收，Markdown 渲染最终回复
- 任务面板：实时显示 Plan / Worker / Critic / Synthesis 状态
- 子任务详情：在面板点击带日志的子任务展开内联日志
- 状态栏：spinner + 当前阶段 + 会话累计 token / 成本

## 待补完（下一轮）

- /memory 子命令（list/search/clear UI）
- profile 编辑（设置抽屉）
- 复制最近回复（按钮）
- 长对话懒加载
- 移动端响应式
- 错误重试 UI
