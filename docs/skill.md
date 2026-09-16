# Skill 接入规范

**文件驱动协议 · 声明式能力。** Skill = 一段可按需加载的 SOP（标准操作流程）。它**不被执行**，而是经 `Skill` 工具把内容注入模型上下文，指导模型接下来怎么做。

## 落点

```
{VANTA_ROOT}/workspace/skills/<name>/SKILL.md
```

`VANTA_ROOT` 默认 `~/Vanta`（环境变量可覆盖）。目录名即 skill 名（也可被 frontmatter 的 `name` 覆盖）。

## 文件格式

`SKILL.md` = YAML frontmatter + markdown 正文：

```markdown
---
name: java-audit
description: Java/Kotlin 项目白盒审计的标准流程。当任务涉及 Java 源码安全审计时加载。
allowed-tools: [shell, knowledge, finding]
argument-hint: "传入目标代码路径"
model: claude-sonnet-4-6
disable-model-invocation: false
user-invocable: true
---

## 适用场景
说明何时用这个 skill。

## 步骤
1. 枚举 sink 函数……
2. 数据流追踪……
3. 判定可利用性并记录 finding……

## 注意事项
- ……
```

### frontmatter 字段（对齐 Claude Code）

| 字段 | 层 | 必填 | 说明 |
|---|---|---|---|
| `name` | L1 | 否 | 规范名，缺省用目录名 |
| `description` | L1 | **是** | 一句话用途。**常驻注入 prompt**，模型据此自行判断是否加载 |
| `allowed-tools` | L2 | 否 | 本 skill 推荐/免确认的工具名列表 |
| `argument-hint` | L2 | 否 | 调用参数提示 |
| `model` | L2 | 否 | 建议模型 |
| `disable-model-invocation` | L1 | 否 | `true` = 不进模型 L1 目录，仅可手动/按名加载。默认 `false` |
| `user-invocable` | L1 | 否 | `false` = 从用户菜单隐藏（预留，暂未接 UI）。默认 `true` |

正文（`## 段落` + 编号步骤）会被 `_parse_sections` / `_extract_steps` 结构化成「执行顺序 + SOP」块。

## 三层加载模型（L1 / L2 / L3）

- **L1** — `description` 由 `preprocess` 注入 system prompt 的「可用 Skill 清单」，模型自动看得见（除非 `disable-model-invocation`）。
- **L2** — 模型调 `Skill` 工具（`{name}`）→ 返回 `描述 + 推荐工具 + 执行顺序 + SOP 正文`。**内容进上下文，不执行。**
- **L3** — skill 目录里的 `references/` 脚本等，L2 响应会附上目录路径，模型用文件工具**按需打开**（渐进披露，避免一次塞爆上下文）。

## 调度链

```
模型判断任务匹配 → 调 Skill 工具(name) → get_provider("skill").get(name)
  → _build_l2_block 组装 → 作为 ToolMessage 回灌 → 模型据 SOP 执行后续
```

`Skill` 工具见 `harness/tools/builtin/orchestration/load_skill.py`；加载器 `get_provider("skill")` 见 `harness/skills/provider.py`（继承 `BaseFileProvider`）。

## 新增一个 skill

1. 建目录 `workspace/skills/<name>/`，写 `SKILL.md`（frontmatter 至少 `description` + 正文）。
2. 无需改代码、无需重启——provider 有 30s TTL 自刷新（或走管理端 CRUD 触发 `reload_all`）。
3. 下一轮对话，模型即在 L1 清单看到它。

## 注意

- `description` 是模型唯一的选择依据，**写清"何时用"** 比写"是什么"更重要。
- Skill 只加载不执行；要"做事"得靠正文里指示模型调工具（工具接入协议）。
- 校验：写入走 CC 标准字段序列化，自定义字段不落盘（写入即收敛为标准）。
