# 后端清理与桌面联调门禁

状态：**代码清理完成，等待真实环境联调**  
更新：2026-09-15

## 已移除

- 未被任何运行入口引用、且已由 `harness/contracts` 取代的 `core/capabilities/utils.py`。
- `resolve_approval` 旧审批捷径；正式路径固定为“认领 → 持久化 → 唤醒工具”。
- `run_agent`、`load_skill`、`get_knowledge`、`search_knowledge`、`Sudo_Bash` 工具别名及运行时分支。
- `ToolRegistry` 中未使用的别名表、全量 LangChain 工具缓存和分类方法。
- 不再驱动任何流程的 `context_compression_enabled` 配置字段。
- 未被调用的 `compiled_graph` 导出；运行时只通过 `get_graph()` 取得当前图。
- MCP `_MCPManagerFacade` 兼容门面；路由直接调用统一 ToolSource 生命周期函数。
- nexus 时代遗留的 Knowledge 数据库/文件双写；数据库是知识条目权威源，Qdrant 是派生索引。
- 已废弃的 Chroma 配置项以及 README 中不存在的 Web 前端说明。

## 保留且仍在使用

- Profile、Memory、Config、Knowledge、Container、MCP 管理接口：它们仍被运行时或能力管理链路引用，不属于死代码。
- PostgreSQL 增量 `ALTER TABLE`：用于升级已有数据库，属于迁移代码，不能当兼容垃圾删除。
- Agent 的 `load_agent`：只加载角色元数据；与真正派发子图的 `Agent` 工具语义不同。
- Tauri 对后端 snake_case 能力字段的反序列化 alias：这是 Python/Rust 协议映射，不是旧接口别名。

## 联调门禁

1. `/health` 必须声明 `api_version=1`；缺失或不匹配时客户端拒绝激活。
2. 钥匙串中已有令牌时，激活连接必须通过 `/auth/me`；401 会清理失效令牌。
3. Python OpenAPI 回归必须覆盖桌面端使用的全部 REST 路径。
4. 前端模块切换保留已访问页面；切换模块不终止对话流，切换连接才销毁页面和订阅。
5. 切换/删除/登出连接前取消并移除该连接的查询；迟到的激活与登录结果不得覆盖当前连接。
6. 前端、Rust、Python 测试、生产构建、全仓 Ruff 与差异检查全部通过后，才进入真实环境联调。

## 真实环境待验证

- PostgreSQL 新表/新列迁移与旧数据回填。
- 登录、过期令牌、审批超时/并发/审计补账。
- 对话流运行中往返 Runs/Artifacts 后继续接收、停止与落库。
- Tauri 下载目录实际写盘，以及 macOS/Windows 安装包。
