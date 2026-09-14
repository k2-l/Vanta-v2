"""Agent 状态定义。

BaseAgentState — 主代理与子代理共用的基础字段。
PenAgentState  — 主代理完整状态（继承 BaseAgentState，附加 L1 上下文/记忆/summary 等字段）。
SubAgentState  — 子代理执行时的独立状态（继承 BaseAgentState，附加子代理特有字段）。
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


def merge_disclosed_tools(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """disclosed_tools 的 LangGraph 累加 reducer：去重合并、保序。

    tool_search 命中的工具名逐轮累积进本集合；用去重版而非裸 operator.add，
    避免同一工具反复披露导致列表膨胀（进而 bound_model cache key 抖动）。
    """
    out = list(existing or [])
    seen = set(out)
    for name in new or []:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


class SubgoalEntry(TypedDict):
    """单条子目标记录。"""

    text: str  # 子目标简短描述
    message_index: int  # 声明时 len(messages)，即该 subgoal 起始消息下标


class BaseAgentState(TypedDict):
    """主代理与子代理共享的基础状态字段。"""

    # ── 对话历史（LangGraph 管理 append）──────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 会话元数据 ────────────────────────────────────────────────────
    session_id: str
    invocation_id: str
    parent_invocation_id: str
    agent_lineage: tuple[str, ...]

    # 每个 Agent invocation 独立计数；父子/兄弟之间不共享余额。
    invocation_tokens: int
    token_limit: int
    force_finalize: bool

    # ── 工具执行日志（每轮重置，供 SSE 事件流使用）─────────────────
    tool_logs: list[str]

    # ── 工具循环检测 ──────────────────────────────────────────────────
    tool_iterations: int  # agent→tools→agent 循环计数
    max_tool_iterations: int  # 循环上限（超出 → recovery）

    # ── 错误恢复 ──────────────────────────────────────────────────────
    error: str | None  # 最近一次错误描述
    error_type: str | None  # TIMEOUT | COMMAND_NOT_FOUND | CONNECTION_FAILED | ...
    recovery_attempts: int  # 已尝试恢复次数
    max_recovery_attempts: int  # 最大恢复次数（默认 3）

    # ── 执行环境 & 追踪 ───────────────────────────────────────────────
    execution_env: str  # "local" | "container:<record-id>"
    trace_id: str  # 请求级追踪 ID，stream_events 入口生成

    # ── 动态工具披露（tool_search）────────────────────────────────────
    # 经 tool_search 命中并解锁的 dynamic 工具名集合（去重累积）。agent 节点
    # rebind 时把这些工具追加到 static 集之外一并绑定，模型方可调用。主图/子图共用。
    disclosed_tools: Annotated[list[str], merge_disclosed_tools]


class PenAgentState(BaseAgentState):
    """主代理完整状态（继承 BaseAgentState）。"""

    # ── 会话元数据（主代理特有）──────────────────────────────────────
    profile: str  # 用户画像
    skill_context: str  # 当前激活的 Skill 内容（注入 system prompt）
    recalled_memories: str  # 召回的长期记忆

    # ── Rolling Summary ────────────────────────────────────────────────
    rolling_summary: str  # 旧消息摘要（替换超出窗口的消息）
    token_count: int  # 当前估计 token 数

    # ── Scratchpad（中间推理暂存区）──────────────────────────────────
    scratchpad: str  # Agent 的草稿区（不写入历史，每轮重置）

    # ── 子目标历史（agent 声明 <subgoal> 标签后追加）─────────────
    # 隐式完成语义：新条目 = 上一条已结束，无需显式"完成"标记
    active_subgoals: list[SubgoalEntry]

    # ── 实体依赖上下文（由 preprocess 填充，注入 system prompt）───
    entity_dep_context: str

    tool_failure_counts: dict[str, int]  # 各工具累计失败次数（整轮会话持续累积）


class SubAgentState(BaseAgentState):
    """子 agent 状态（继承 BaseAgentState，附加子代理特有字段）。

    子 agent 是完全隔离的执行单元：
      - 独立消息历史（从任务描述开始，不携带主代理对话历史）
      - 继承 session_id / trace_id（用于计费追踪 + 链路追踪）
      - 不携带主代理的记忆、画像、skill 上下文
    """

    # 子代理标识
    agent_name: str  # 当前子 agent 名称
    agent_depth: int  # 调用深度（1=主代理派发，最多到配置的 depth=3）

    # ── Critic 质量门（enable_critic 时启用，由 critic_node 写入）───
    critic_attempts: int  # 已重试次数（上限 2，见 critic_node）
    critic_passed: bool  # True = 质量达标或已耗尽重试次数，路由到 END
