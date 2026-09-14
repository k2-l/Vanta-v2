# 近期功能新增说明：多 Provider · 跨模型 · 远程客户端

> 范围：本文件只记录**这几轮新增的功能**及其目标，不含更早的 bug 复核/整改（见 `orchestration-review.md`、`orchestration-remediation-plan.md`）。
> 一句话总目标：把 Vanta 从「**单一 Anthropic 厂商 + 单一部署形态**」升级为「**多厂商、可跨模型、可远程桌面访问**」的产品形态。

---

## 功能一：多 API 兼容 + 统一协议路由（Anthropic / OpenAI）

**要解决什么**
原来所有模型只能走 Anthropic 协议（`ChatAnthropic`），被单一厂商与单一接口锁死。目标是同时支持 **Anthropic 与 OpenAI 两种 API 协议**，并能自动判断某个模型该走哪条协议。

**做了什么**
- 新增 provider 抽象层 `harness/core/graph/providers.py`，把所有厂商差异收敛到一处，图节点保持 provider 无关：
  - `infer_provider(model)`：按模型名前缀**智能推断**（`claude*`→anthropic，`gpt*/o1/o3/o4*`→openai，都不中回退 `default_provider`）。
  - `resolve_provider(explicit, model)`：**显式 provider 优先（手工）**，缺省则智能推断；非空非法值直接拒绝，避免静默改投其他厂商。
  - `build_chat_model(...)`：按 provider 构造 `ChatAnthropic` / `ChatOpenAI`，凭据按 provider 取。
  - `supports_prompt_cache` / `supports_thinking`：Anthropic 专属能力开关（对 OpenAI 强制关闭 `cache_control` 与 `thinking`，否则端点报错）。
  - `extract_usage(resp)`：跨 provider 归一 token 用量（优先 LangChain `usage_metadata`，回退 Anthropic 原生字段）。
- 全链路接入：主代理 / 子代理 / critic / 摘要压缩 / 标题生成 / 审计 Agent 全部改走 provider 层。
- 新增依赖 `langchain-openai`（实测其 `bind_tools` 直接吃现有 Anthropic 格式工具 dict，工具层零改动）。

**涉及文件**
`core/graph/providers.py`（新）、`core/graph/models.py`、`core/graph/nodes/agent.py`、`core/graph/nodes/tools.py`、`core/graph/subagent/nodes.py`、`core/context/summarize.py`、`core/capabilities/services.py`、`security/audit_agent.py`。

---

## 功能二：跨模型主 / 子代理（智能选择 + 手工选择）

**要解决什么**
让「主脑」和「执行者」可以用**不同厂商、不同档位**的模型。典型场景：主代理用 Anthropic Opus-4-8 做大脑，子代理用 OpenAI GPT-5.5 做执行者。

**做了什么**
- 当前执行链按职责使用档位：主代理使用 mid，摘要/标题/critic/审计使用 low；各调用点均优先使用对应档位的 provider 覆盖，缺省再按模型名推断。high 档保留为后续高级任务选型入口，当前没有调用方。
- 子代理按 agent frontmatter 的 `model` + 新增 `provider` 字段选，支持逐 agent 跨 provider。
- 契约层 `EntityFull` 增加 `provider` 字段，frontmatter 解析/序列化同步支持。

**涉及文件**
`contracts/models.py`、`contracts/frontmatter.py`、`agents/provider.py`、`core/graph/subagent/nodes.py`（子代理选型）、`core/graph/nodes/agent.py`（主代理选型）。

**用法（agent frontmatter）**
```yaml
---
name: executor
description: 执行类子代理
model: gpt-5.5
provider: openai      # 手工选择；省略则按 model 名智能推断
---
```

---

## 功能三：Bearer / OAuth Token 访问（Anthropic 协议）

**要解决什么**
除 `x-api-key` 外，支持用 **Bearer/OAuth token**（如 Claude Code OAuth token、Bearer 风格代理网关）访问 Anthropic 协议端点。同时修掉一个回归：`anthropic_auth_token` 曾一度成为「启动通过但调用必失败」的配置陷阱。

**做了什么**
- `build_chat_model` 的 anthropic 分支**优先走 Bearer**：`auth_token` 存在 → `default_headers: Authorization: Bearer <token>`，且**不发 x-api-key**；否则用 api_key。
- 实测 `ChatAnthropic` 可用 Bearer-only 干净构造（不读环境、不带 x-api-key）。

**涉及文件**
`core/graph/providers.py`。

> 说明：这是支持 **Bearer/OAuth 这种凭据形式**，token 需你通过官方许可方式获取；**不等于**"用消费级订阅账号密码登录"，本平台不做订阅账号登录代理。

---

## 功能四：多 Provider 配置面（API 可配 + 凭据校验放宽）

**要解决什么**
让上面三项**在产品层真正可配**——不用手改 `config.toml` 就能设置 OpenAI 凭据与各档 provider；并允许**纯 OpenAI 部署**（不再强制 Anthropic 凭据）。

**做了什么**
- `routes/config.py` 的可编辑白名单补齐：`openai_api_key`、`openai_base_url`、`default_provider`、`model_high/mid/low_provider`；敏感字段加 `openai_api_key`（GET 脱敏）。
- `settings.py`：新增 `[openai]` 凭据、`default_provider` 与三档 provider 覆盖字段及其 TOML 加载；启动校验 `_check_credentials` 放宽为**「至少一个 provider 凭据即可」**。
- provider 配置统一规范化为小写并限定为 `anthropic | openai`；配置 API、模型工厂与 Agent frontmatter 均对非法值 fail-fast。

**涉及文件**
`routes/config.py`、`infra/settings.py`。

**配置示例（`data/config.toml`）**
```toml
[anthropic]
api_key    = "sk-ant-..."      # 或
auth_token = "..."             # Bearer/OAuth（二选一，现已生效）

[openai]
api_key  = "sk-..."
base_url = ""                  # 可选，指向 OpenAI 兼容端点

[models]
high = "claude-opus-4-8"
mid  = "claude-opus-4-8"
low  = "claude-haiku-4-5-20251001"
default_provider = "anthropic" # 智能推断兜底
mid_provider     = "anthropic" # 可选，手工钉死更稳
```

---

## 功能五：前端远程瘦客户端寻址（为 Win/Mac 桌面壳铺路）

**要解决什么**
产品要适配 Win/Mac，路线定为「**后端留在 Linux（远程），Win/Mac 桌面端做瘦客户端**」。原前端 base URL 是构建期固定/同源，无法作为远程客户端连任意后端。

**做了什么**
- base URL 收敛为**运行期可配的单一真相源**：`store/auth.ts` 新增持久化的 `serverUrl` + `serverBase()` / `wsBase()`（`http→ws`、`https→wss` 自动派生）。
- `api.ts` / `sse.ts` / `ws.ts` 三处硬编码寻址改为调用期取 `serverBase()`/`wsBase()`。
- 登录页 `LoginPage.tsx` 增加「服务器地址」输入框（同域部署留空即可）。
- 后端默认 CORS 放行 Tauri webview origin（`tauri://localhost` 等）。

**涉及文件**
`web/src/store/auth.ts`、`web/src/shared/lib/{api,sse,ws}.ts`、`web/src/app/LoginPage.tsx`、`infra/settings.py`（CORS 默认值）。

> 现状：前端这部分**已按用户要求暂缓推进**，桌面壳（Tauri）脚手架与 TLS/WSS 部署为后续；后端已就绪。

> 配置界面同样暂缓：当前 OpenAI 凭据、档位 provider 与逐 Agent provider 已可通过后端 API / Agent frontmatter 配置，但尚未加入 ConfigPage / AgentPage 表单。

---

## 附：清理与测试

- **清理**：删除已无调用方的 `harness/infra/anthropic.py`（`build_anthropic_client`）——标题生成、审计 Agent 已迁到 provider 层。
- **测试**：`tests/test_orchestration_remediation.py` 增加 provider 路由 / Bearer 头接入 / 凭据校验 / frontmatter provider 解析等用例；测试数量与结果以实际测试命令输出为准，避免文档中的固定计数随新增用例失真。

---

## 目标全景与后续

**这几轮共同要实现的产品能力**：
1. **不锁厂商**：Anthropic / OpenAI 双协议，按模型名智能路由 + 可手工指定。
2. **可跨模型编排**：主脑与执行者用不同厂商/档位的模型各司其职。
3. **凭据形态灵活**：api_key / Bearer-OAuth / 纯 OpenAI 部署皆可，且产品层可配。
4. **可远程桌面访问**：后端留在 Linux，Win/Mac 做瘦客户端（前端地基已铺，桌面壳待做）。

**尚未做（延后项）**：
- OpenAI reasoning 模型的 `max_completion_tokens` 兜底与 reasoning effort 接入。
- 端到端真实 OpenAI 端点联调。
- Tauri 桌面壳脚手架 + 打包 + TLS/WSS 部署。

> 以上改动**均未 git commit**，待用户明确发话后再提交。
