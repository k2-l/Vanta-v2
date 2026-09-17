# MCP 接入规范

**工具接入协议 · 可执行动作 · 接入驱动（零代码）。** MCP（Model Context Protocol）server 是外部 stdio 子进程，Vanta 把它暴露的每个远端工具**包装成本地 `Tool`**（名为 `mcp__<server>__<tool>`），落进同一 `registry`。接入一个 MCP server 只需**配置**，不写代码。

## 两种接入方式

### 1. 启动配置（`data/config.toml`）

```toml
[[mcp.servers]]
name    = "filesystem"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
# env   = { API_KEY = "xxx" }   # 可选，注入子进程环境
# enabled = true                # 可选，默认 true
```

启动时 FastAPI lifespan 调 `init_mcp_tools()` 逐个拉起、`initialize` 握手、`tools/list`，注册工具。单个 server 失败只 warning，不影响其余 server 与主服务。

### 2. 运行时热挂载（REST，无需重启）

管理端 `harness/routes/mcp.py`：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/v1/mcp/servers` | 列出（持久配置骨架 + 运行时状态合并视图） |
| `GET` | `/v1/mcp/servers/{name}` | 查看单个 Server 及已注册工具明细（env 只返回键名） |
| `POST` | `/v1/mcp/servers` | 新增 + 热挂载（请求体须带 `confirm: true`） |
| `PATCH` | `/v1/mcp/servers/{name}` | 更新配置并热重载（请求体须带 `confirm: true`；省略 `env` 时保留原值） |
| `DELETE` | `/v1/mcp/servers/{name}` | 热卸载（drain 延迟关子进程）+ 从配置移除（请求体须带 `confirm: true`） |
| `POST` | `/v1/mcp/servers/{name}/test` | 临时拉起验证连通性，用完即关，不入册 |

env 脱敏：`GET` 只回 env 的 key 名，不回明文 value。

## 接入后的行为

- 远端工具注册为 `mcp__<server>__<tool>`，`category="mcp"`，**`disclosure="dynamic"`**——藏在 `tool_search` 之后，多 server 时不撑爆 prompt。模型需先 `tool_search` 搜到再调用。
- 工具集变化后 `registry.tools_hash()` 自动变，agent 绑定模型的 cache key 随之失效，下一轮对话即看见/看不见增删的工具。
- **自愈**：子进程死掉时按需重连（带冷却间隔），已注册工具持有的 client 引用不变，无需重注册。
- **热卸载 drain**：卸载立即摘工具，子进程延迟 5s 关闭，给 in-flight 调用留窗口。

## 底层：统一来源协议

MCP 走的是工具接入协议的统一来源接入（`harness/tools/source.py`）：

```
每个 MCP server = 一个 MCPSource(ToolSource)   # id = mcp:<name>
  discover() → 拉起 MCPClient + tools/list → 产出 MCPTool 列表
  aclose()  → 关子进程
  ↓
ToolSourceCoordinator 统一注册/卸载/重载，drain 延迟由它负责
```

MCP 生命周期函数（`harness/tools/mcp/__init__.py`）直接委托给 `coordinator`。见 [plugin.md](./plugin.md) 了解同一套 `ToolSource` 协议如何接入 plugin。

## 新增一个 MCP server（清单）

1. 写 `[[mcp.servers]]` 配置（或走 `POST /v1/mcp/servers`，带 `confirm:true`）。
2. `command`/`args` 指向可执行的 MCP server（stdio）。
3. 启动 / 热挂载后，工具以 `mcp__<name>__*` 出现；模型经 `tool_search` 发现调用。

## 注意

- `name` 不要含 `__`（会与 `mcp__<server>__<tool>` 命名前缀冲突，管理端有撞名检查）。
- 敏感值放 `env`，不进明文视图；真正的密钥/凭据传递用 vault 引用（见 `harness/security/secrets_vault`）。
- MCP 工具与内置工具在 `registry` 里平权，执行时同样过超时/scope/审批门。
