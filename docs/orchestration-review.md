# Vanta 编排系统问题分析报告

> 范围：`harness/core/`（图/节点/上下文/子图/运行时）为主，旁及 `tools/`、`security/`、`web/` 相关衔接点。
> 方法：静态阅读 + 调用链追踪。每条含**定位、证据、影响、建议**。严重度分 `高 / 中 / 低`。
> 校验：末尾「二次校验结论」由独立 agent 复核后回填。

---

## 一、Bug（真实缺陷）

### B1. `<scratchpad>` 内容泄露给用户并写入 DB / 记忆 — 中
- **定位**：`harness/core/graph/nodes/agent.py:26-30`（提示"内容不会直接展示给用户"）、`:221-225`（仅抽取到 state，不从正文剥离）；`harness/core/runtime.py:509-517`（流式原样 `TextDelta` 发送）；`web/src/features/chat/components/MessageList.tsx:15-19`（前端只剥 `<subgoal>`，**不剥 `<scratchpad>`**）。
- **证据**：`agent_node` 用 `_SCRATCHPAD_RE.search` 把 scratchpad 存进 state，但 `content_str` / `response.content` 未做任何删除；runtime 的 `on_chat_model_stream` 把整段 content（含 `<scratchpad>…</scratchpad>`）逐 token 作为 worker 文本发给前端，并累加进 `final_text`（后续落 DB + 向量记忆）。前端 `stripSubgoals` 只处理 subgoal，无 scratchpad 处理（`grep scratchpad web/src` 为空）。
- **影响**：系统承诺的"私有草稿区"实际全程可见并持久化，违背设计契约；草稿噪声污染历史与长期记忆。
- **建议**：在 `_extract_text` 后、发送前统一 strip `<scratchpad>…</scratchpad>`（后端流式需处理未闭合尾标签），或前端补一个 `stripScratchpad`。

### B2. Critic 质量门是死代码（且是"半接线"死代码）— 中
- **定位**：`harness/core/graph/subagent/build.py:42` 硬编码 `build_sub_agent_route_after_agent(False)`，且未 `add_node("critic", …)`。
- **证据**：`critic_node`、`route_after_sub_agent_critic`、`_CRITIC_PROMPT_TEMPLATE`（`subagent/nodes.py:332-415`、`routes.py:135-139`）无任何生产调用路径；`runtime.py:77-81` 仍在按 `node != "critic"` 过滤一个永不存在的节点。
- **⚠ 复核补充（比原判更严重）**：`enable_critic` 一路铺到了 **DB 列 + API patch**（`harness/routes/agents.py:88`、`:242`），用户可在界面上开关它，但 `build_sub_graph` 完全无视该值——是"接了线却不通电"的半成品，比纯死代码更具误导性。
- **影响**：`SubAgentState.critic_attempts/critic_passed`、界面开关、相关文档描述的"回复质量门"功能实际全部无效。
- **建议**：要么让 `build_sub_graph` 读取 agent 的 `enable_critic` 并真正 `add_node("critic")` + 接 `route_after_sub_agent_critic`，要么删除死代码、state 字段、DB 列与 API。

### B3. 子 Agent 无法再派发，depth=2 调度链为不可达逻辑 — 中
- **定位**：`harness/core/graph/subagent/nodes.py:48-52` `_MAIN_AGENT_ONLY_TOOLS = {"Agent"}`；`harness/infra/settings.py:435` `sub_agent_max_depth = 2`；orchestrator 提示 `nodes/agent.py:56-58`。
- **证据**：`Agent` 工具是主代理专属，子 agent 调用会被 `_execute_subgraph_tool_call` 拦截（`nodes.py:176-188`）。因此 `enter_sub_agent_depth` 永远只能到 depth=1，`agent_depth=2`（"孙"/协调者）不可达。但 `_ORCHESTRATOR_HINT` 明确宣传"复杂流程可派给具有调度能力的指挥官 Agent，由它负责内部调度"。
- **影响**：文档/系统提示承诺的"委托协调 / 多层调度"能力实际不存在，模型可能据此产生无效计划；深度上限相关配置与 state 字段（agent_depth=2 分支）为死逻辑。
- **建议**：明确取舍——要么允许特定"指挥官"agent 使用 `Agent`（白名单放行），要么从提示与配置中移除多层调度承诺。

### B4. 预算只在回合开始检查，回合内不再校验；默认配置下几乎无上限 — 中高
- **定位**：`harness/core/graph/nodes/preprocess.py:78-96`（仅 turn 开始 `check_budget`）；`settings.py:423` `max_tool_iterations = 0`、`:372` `max_tool_calls_per_turn = 0`；`routes.py:66-73`（`max_iter>0` 才触发循环打断）。
- **证据**：`check_budget` 只在 preprocess 执行一次；`record_usage` 每次 LLM 调用累加但不再触发预算判断。默认 `max_tool_iterations=0`（不限）→ `route_after_agent` 的循环打断分支永不进入 → 唯一兜底是 `graph_recursion_limit=500` 与 turn 间预算。单个回合最多可跑约 `500/2 ≈ 250` 轮工具循环，其间 token 预算完全不生效。
- **影响**：一次失控回合可远远超出 `session_token_limit` 才停止；预算"兜底"在最需要它的长回合里失效。
- **建议**：在 `agent_node`/`route_after_agent` 内周期性调用 `check_budget`（或基于 `state['token_count']` 做软阈值），预算超限时走 recovery→END。

### B5. 软上限（SOFT_LIMIT_REACHED）不重置 `tool_iterations`、不增 `recovery_attempts` — 中
- **定位**：`harness/core/graph/nodes/recovery.py:30-43`；`routes.py:95-98`（SOFT_LIMIT → 回 agent）。
- **证据**：命中软上限后注入"总结并询问用户"消息，但 `tool_iterations` 保持 ≥ 上限、`recovery_attempts` 不变。若模型未遵从、继续发起 tool_call，`route_after_agent` 立即再判超限 → recovery → 又 SOFT_LIMIT，循环往复，仅由 `graph_recursion_limit` 兜底。
- **影响**：弱循环护栏；"询问用户是否继续"后本回合无法真正提升步数（继续依赖新回合重置），且存在打转风险。
- **限定（复核）**：打转**高度条件化**——需 `max_tool_iterations>0`（非默认，默认 0 时该分支根本不触发），且模型无视"总结并询问"注入指令继续调工具；即便发生也被 `graph_recursion_limit=500` 兜底，**非无界死循环**。代码事实（不重置/不自增/回 agent）属实。
- **建议**：软上限计数并入 `recovery_attempts` 或单独计数，达到 N 次后强制 END；或在软上限后临时抬高本回合 `max_tool_iterations`。

### B6. 并行子 Agent 的流式 token 交错为一路输出 — 中
- **定位**：`harness/core/runtime.py:294-350`（drain `sub_event_queue`）；`subagent/runtime.py:78-87`（所有子 agent 事件入同一队列）。
- **证据**：`_ORCHESTRATOR_HINT` 鼓励"同一轮回复中调用多个 Agent"并行；`tool_node` 用 `asyncio.gather` 并发跑多个子 agent，它们的 `on_chat_model_stream` 全部 put 进同一个 `sub_event_queue`，主流一律以 `TextDelta(role="worker")` 发出，文本层面无按 agent 名分隔。
- **影响**：并行多子 agent 时，用户看到多份回答逐 token 交错混排，几乎不可读；`_sub_streamed[agent_name]` 只用于去重尾部，不解决交错。
- **建议**：TextDelta 携带 `agent_name`/`task_id`，前端按来源分栏渲染；或串行化子 agent 的文本冒泡。

### B7. `final_text` 累加所有轮次的 agent 文本并持久化 — 中低
- **定位**：`harness/core/runtime.py:515-516`（每轮流式累加）、`:583-594`（落 DB + 记忆）。
- **证据**：`_run_streamed` 每进入 `agent` 节点重置，但 `final_text` 跨"agent→tools→agent"多轮持续累加。多轮任务里，中间轮的解释性文本也被拼进最终 assistant 消息，写入 DB 与向量记忆，下一回合作为历史重放。
- **影响**：assistant 历史/记忆包含中间过程噪声，长任务尤甚；与 scratchpad 泄露叠加放大。
- **建议**：只持久化"最终无 tool_call 那一轮"的文本，或按轮次分段、仅保留结论段。

### B8. `run_agent` 整体重试会重复执行子 agent 的副作用 — 中
- **定位**：`harness/tools/builtin/orchestration/run_agent.py:122-163`。
- **证据**：瞬时错误下对 `run_sub_agent` 整体重试至多 3 次（指数退避），而子 agent 图内部已自带 recovery 重试。整体重试会**从头重跑**子 agent：已执行过的工具（Bash/扫描/WebFetch）、审计账本落账、记忆写入都会再来一遍。
- **影响**：双层重试成本叠加；对渗透/命令类动作可能重复执行有副作用甚至破坏性的操作，且重复刷审计账本。
- **建议**：区分"未产生任何副作用的早期失败"才整体重试；有副作用后失败应直接返回，交由主代理决策。

### B9. `turn_cost` 成本估算只用主模型单价 — 低（有意简化）
- **定位**：`harness/core/runtime.py:631-632`。
- **证据**：`turn_in/turn_out` 汇总了主代理 + 所有子 agent + critic/压缩（`model_low`、`agent.model`）的用量，但单价固定取 `_get_price_table().get(s.model_mid)`。
- **影响**：多模型场景下 `turn_cost_usd` 系统性偏差（子 agent 用不同价位模型时尤甚）。
- **限定（复核）**：`usage.py` 已注明成本"仅参考"、`UsageEvent` 亦标 `model=model_mid`，属**有意的单价简化**而非隐蔽缺陷。若要精确才需改。
- **建议**：`record_usage` 已按 model 记账，成本应按 model 分组汇总后求和。

### B10. 预算百分比可除零 — 低（潜在，非活跃）
- **定位**：`harness/core/context/budget.py:136-141`（`used / s.session_token_limit * 100` 等）。
- **证据**：若 `session_token_limit` 或 `daily_token_limit` 被配成 0，`get_budget_status` 抛 `ZeroDivisionError`，预算查询接口 500。
- **限定（复核）**：默认值为百万/千万级（`settings.py:392-393`），**仅在人为把 limit 配成 0 时触发**，属潜在缺陷而非现存 bug。
- **建议**：分母为 0 时百分比按 0 或 100 处理，或校验配置下限。

---

## 二、不合理 / 可优化逻辑

### O1. 非 engagement 期间工具大输出落盘不脱敏 — 低中
- **定位**：`harness/core/graph/tool_exec.py:183-190`（`redact` 仅 `xenv.has_engagement` 时执行）、`_persist_and_truncate` 无条件写全文到 `workspace/.tool_outputs/`。
- **影响**：非授权作业场景下，工具输出中的密钥/凭据以明文落盘。
- **建议**：落盘前对全文统一做一次基础脱敏，或对落盘目录加访问限制/清理策略。

### O2. `tool_failure_counts` 提示计数在并行调用下不精确 — 低
- **定位**：`harness/core/graph/nodes/tools.py:129-137`。
- **证据**：`new_count = failure_counts.get(tool_name,0)+1` 在各并发 task 内独立计算，同名工具同轮多次失败时都取到相同基数，提示里的"已累计失败 N 次"不准；真正累加在外层 `new_failure_counts`（`:232-234`）另算。
- **建议**：提示阈值判断改为读取合并后的计数，或以最终计数生成提示。

### O3. 中文 token 估算严重偏低 — 低
- **定位**：`harness/core/graph/nodes/preprocess.py:126-134` 使用 `estimate_tokens`（len//4）。
- **证据**：中文约 1–2 字符/token，len//4 会低估 2–4 倍。虽注释声明"仅供观测、不参与控制流"，但日志/前端预算展示会误导。
- **建议**：对 CJK 用更接近的系数（如 len//1.5），或保留 tiktoken 的懒计算路径。

### O3b. 历史截断可能丢失未被任何摘要覆盖的消息 — 低中
- **定位**：`harness/core/runtime.py:210-231`。
- **证据**：无压缩检查点的存量会话回退"最近 N 条"，再按 `history_token_budget` 从头丢弃；被丢弃的消息不一定在 `rolling_summary` 内（摘要为用户主动触发才生成），造成静默上下文丢失（仅 `log.warning`）。
- **建议**：截断触发时提示用户先压缩，或对被丢弃段做即时轻量摘要注入。

---

## 三、验证优先级建议
高置信可直接确认：B1、B2、B3、B4、B9、B10、O2、O3。
需运行/构造场景确认表现：B5、B6、B7、B8、O1、O3b。

---

## 二次校验结论

由一名**独立 agent**（全新上下文，非 fork）逐条对照源码复核，结论如下：

**全部 14 条均判定「成立」**，与源码一致。其中 B1 / B2 / B3 证据充分、结论最稳固。

需加限定/降级的 4 条（已在正文对应条目补注）：
- **B5**：打转风险成立但**高度条件化**（需 `max_tool_iterations>0` 非默认 + 模型抗指令 + 有 recursion 兜底），非无界死循环。
- **B9**：偏差属实，但属 `usage.py` 已声明的**有意"仅参考"简化**。
- **B10**：结论成立但**默认配置不触发**，应视为潜在缺陷。
- **O2**：真实但**边角轻微**，核心 `tool_failure_counts` 仍由外层正确累加，仅失败提示阈值略有偏差。

复核额外发现（已并入 B2）：`enable_critic` 竟铺到了 **DB 列 + API**（`routes/agents.py:88/242`）却被 `build_sub_graph` 无视——比"纯死代码"更严重的"半接线"状态。

> 结论：报告无「不成立」条目；建议优先处理 **B1（隐私契约违背）、B2（半接线死代码/误导）、B3（能力宣传与实现不符）、B4（预算失效）** 与 **B8（子 agent 副作用重复执行，对渗透场景有实操风险）**。
