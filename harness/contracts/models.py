"""实体（Agent / Skill）的统一数据模型。

对齐 Claude Code：
  - L1（EntityMeta）：name + description，常驻 system prompt，
    模型据 description 自行判断是否使用——没有 keywords / patterns / 路由信号。
  - L2（EntityFull 及子类）：正文 + 各域专属字段，按需加载。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════
# L1 · 轻量索引项
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EntityMeta:
    """L1 元数据（对齐 Claude Code：name + description + 调用控制）。"""

    name: str
    description: str
    disable_model_invocation: bool = False  # CC: true=模型不自动加载（不进模型 L1 目录），仅手动
    user_invocable: bool = True  # CC: false=从用户 / 菜单隐藏（预留，暂未接 UI）


# ═══════════════════════════════════════════════════════════
# L2 · 全文（基类 + 两域子类）
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EntityFull:
    """L2 全文基类。"""

    meta: EntityMeta
    content: str  # SKILL.md / AGENT.md 正文
    model: str | None = None
    path: str = ""  # 实体目录；L3 渐进披露（references/ 等）靠它定位


@dataclass(frozen=True)
class AgentFull(EntityFull):
    """Agent 全文。字段对齐 Claude Code subagent frontmatter。

    CC 标准字段：name/description + disable-model-invocation/user-invocable（在 meta）·
    model（在基类）· tools。
    """

    tools: list[str] = field(default_factory=list)  # CC: 子 agent 可用工具白名单


@dataclass(frozen=True)
class SkillFull(EntityFull):
    """Skill 全文。字段对齐 Claude Code skill frontmatter（custom command 已并入 skill）。

    CC 标准字段：name/description + disable-model-invocation/user-invocable（在 meta）·
    model（在基类）· allowed-tools · argument-hint。
    """

    allowed_tools: list[str] = field(default_factory=list)  # CC: 本轮免确认工具
    argument_hint: str | None = None  # CC: 自动补全的参数提示
