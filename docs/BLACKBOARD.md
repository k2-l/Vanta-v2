# Vanta 结果看板 + 密钥安全传递 施工图

> **目标**：给多 agent 协作补一块**持久、可查、带权限的结果看板（blackboard）**——上游产出（发现 / 扫描结果 / 报告）挂上去，下游按需取；并解决其中最尖的**密钥/敏感信息传递**问题（要能传给下游、又绝不泄露给 LLM）。
>
> 本文件是**照表施工依据**（同 `docs/RESTRUCTURE.md` 风格）。未 commit，随实现一并提交。

## 1. 背景 / 为什么

- 现状：多 agent 串行时，上游结果只能靠 `run_agent(name, task, context="…")` 的 `context` 参数**手动塞**给下游，无持久、无查询、无权限。
- 想要：一个**看板**——产出挂上去、下游按需取。这是经典 **blackboard 模式**。
- 难点 = **权限**：不能让每个 agent 随便拉全部数据；尤其（凭据 / 密钥 / 敏感信息）既要能往下传、又不能进 LLM 的"视野"（一进上下文就可能顺日志 / 模型厂商 / prompt 注入漏出去）。

## 2. 两条定调原则

1. **能力 = 编排 → 默认走「编排层中介」**：看板是持久 artifact 库；**由父 agent 按工作流把"该给下游的那一片"注入进它的 `context`**，agent 不自助 full-pull。权限是**代码强制**的一个点，不靠 agent 自觉。
2. **密钥 = 传引用不传真值（取件码 / handle）**：agent 与看板全程只流转 `secret://` 引用；真值只在**工具执行的沙箱边界、调用发生的那一刻** resolve 注入进程，LLM / 日志 / 看板从不见明文。业界共识（见 §7）。

## 3. 数据模型：`Artifact`（泛化现有 `SecurityFinding`）

现有 `harness/infra/db.py::SecurityFinding`（`engagement_id/title/severity/category/target/evidence/remediation/status/created_at`）就是"看板"的一个特例。

**P1 取向（已定）：原地扩 = 扁平超集，零删除、零迁移。** 直接给现有 `security_findings` 表**加**下列新列（配 `init_db` 的 `ALTER TABLE ADD COLUMN` 兜底）；表名保持 `security_findings`，加 `Artifact = SecurityFinding` 别名。**没有旧字段被删**：`evidence` 直接当通用正文（不另加 `content`）；finding 专属列 `severity/category/target/remediation/status` 对非-`finding` 的 kind 置空即可（它们仍被 finding/report 工作流使用）。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `engagement_id` | 归属 engagement（**L1 隔离边界**，index） |
| `producer` | 产出方（agent name / session_id） |
| `kind` | `finding` / `scan_result` / `recon` / `report` / `note` / `secret_ref` |
| `sensitivity` | `public` / `internal` / `secret` |
| `tags` | JSON list（供筛选） |
| `content` | 正文（**`secret` 类不存明文**，只存脱敏摘要 + `vault_ref`） |
| `vault_ref` | `secret://<name>`，指向 `secrets_vault` 的引用（仅 secret 类） |
| `share_with` | JSON list（角色 / agent 白名单；空 = 按 `sensitivity` 默认策略） |
| `dedup_key` | 去重键 |
| `status` / `created_at` | 同 finding |

## 4. 权限矩阵（分层，全复用现有护栏）

| 层 | 规则 | 复用 / 落点 |
|---|---|---|
| **L1 engagement 隔离** | 只见本 engagement 的 artifact；跨域天然不可见 | `ExecEnv.engagement_id`（和 egress 沙箱同一边界，免费） |
| **L2 条目标签** | 每条带 `kind` + `sensitivity` + `producer` + `share_with` | Artifact 新增字段 |
| **L3 访问策略** | 可读 = 消费者声明的需要 ∩ 生产者 `share_with` ∩ `sensitivity` 门槛 | `board.read` 过滤 + agent frontmatter 声明 `board_access` |
| **L4 密钥** | secret 不进看板正文；走 `vault_ref` + **resolve-at-exec**（§5） | `secrets_vault` + §5 |
| **L5 审计** | 每次 `board.read` / `secret.resolve` 记账 | `audit_ledger.append_audit()` |

**消费模式（二选一，建议默认 ①）**：
- **① 编排中介（推荐）**：父 agent 用 `run_agent(name, task, context=board.slice(scope…))` 注入下游 —— **一个强制点**，下游 agent 拿不到未授权数据。契合"能力=编排"。
- **② 受限自助**：给 agent 一个 `board.read(query)` 工具，agent 在 frontmatter 声明 `board_access`（`kind`/`sensitivity` 白名单），工具按 L3 过滤。灵活、但攻击面更大，只给探索型 agent。

## 5. 密钥 handle 生命周期（取件码机制）

**现状**（`harness/security/secrets_vault.py`）：已有 per-engagement Fernet 加密库 `set_secret / get_secret / list_secret_names / delete_engagement_secrets`；但 `get_secret` **返回明文**、无 handle、无 resolve-at-exec。要补的是"引用层 + 执行边界注入"：

1. **存**：上游 `set_secret(eng, name, value)` → 拿引用 `secret://<name>`（scoped 到本 eng）；看板 / agent 只传**引用 + 脱敏摘要**。
2. **授予**：引用授予是 scoped —— 绑本 engagement + 指定消费者 + 可选 **TTL / 一次性**（记在 `Artifact.share_with` 或一张 grant 表）。
3. **用**：下游在工具调用里写占位 —— `curl -u admin:{{secret:<name>}} 目标`，或 env `-e PASS={{secret:<name>}}`。
4. **resolve**：**执行层**（`harness/tools/builtin/cmd/shell.py` 的沙箱分支 / `security/sandbox.py::build_entrypoint`）在**沙箱内**把占位换成 `get_secret` 真值再跑；先校验（消费者 + eng + grant + 可选 approvals）。真值只活在子进程 env/stdin，进程退出即消失。
5. **回**：输出经 `redaction.redact()` 脱敏才回 LLM。
6. **审计**：`append_audit("secret.resolve", ref=…, consumer=…, eng=…)` —— **记引用不记真值**。

**配套改造**：
- `redaction`：现只按 **pattern** 打码 → 加"**按已知 active-engagement 密钥真值精确 mask**"，挡 `echo $secret` 这类无 pattern 的回显外泄。
- 沙箱已 **egress 锁死**（挡网络外泄）+ `capsh` 丢权 —— 两条一起，单层都不够（NVIDIA 红队结论：光断网不够，密钥还在视野里 LLM 能直接念出来）。
- 高敏首次 resolve → `approvals` HITL 门。

## 6. 复用 vs 新增（照表）

| 已有（复用） | 新增 |
|---|---|
| `secrets_vault`（加密存 + get/set） | `secret://` 引用 + resolve-at-exec 钩子（shell.py / sandbox） |
| `redaction`（pattern 打码） | + 按已知真值精确 mask |
| `sandbox`（egress / cap 边界） | 占位注入点 |
| `audit_ledger`（哈希链记账） | board / secret 读用记账 |
| `SecurityFinding` | 泛化 `Artifact` 表 + `board` 工具 |
| `run_agent(context=…)` 手动串 | `board.slice()` 注入 +（可选）`board.read` 工具 |
| `approvals` | 高敏 resolve 门 |

## 7. 依据（业界最佳实践）

- **金句**：「不想 AI 泄露密钥，就别把密钥给它」(Auth0)；控制必须放在**模型控制面之外**(NVIDIA)。
- **运行时注入 / credential broker**：执行层取密钥、只把结果回给 LLM(Doppler / NVIDIA)。
- **存引用而非真值 + 短命 + 租约**(HashiCorp Vault dynamic secrets / lease)。
- **日志打码 + 别全信自动检测**(GitHub Actions masking)。
- **反面教材**：Devin token 外泄、Claude Code DNS 偷传 key(CVE-2025-55284)、OWASP LLM07 System Prompt Leakage。

## 8. 分期（每期独立可验 / 可回滚）

| 期 | 内容 | 验证 |
|---|---|---|
| **P1** | `Artifact` 表 + `board.write/read` 工具（kind/sensitivity/tags）+ L1/L2；`SecurityFinding` 归为 `kind=finding` | 起栈：产 / 取 artifact 通；跨 engagement 隔离生效 |
| **P2** | L3 策略：agent frontmatter `board_access` 声明 + `board.read` 过滤；编排中介 `board.slice()` 注入 `run_agent` | 越权读被拒；父 agent 注入切片可用 |
| **P3** | 密钥 handle：`secret://` 引用 + shell.py resolve-at-exec + redaction 真值 mask + audit | 明文不进 LLM / 日志；回显被 mask；egress 挡外传 |
| **P4** | 高敏 `approvals` 门 + TTL / 一次性 grant + 看板 UI（可选） | HITL 生效；grant 过期失效 |

## 9. 施工提示

- **核实优先**：先读真实模块再动；护栏 / 密钥相关改动必带测试。
- 任何"真值可能进 LLM 上下文 / 日志"的路径都要过 `redaction`。
- 新代码**默认假设 agent 有敌意**（prompt injection）——防线放执行边界，不放提示词。
