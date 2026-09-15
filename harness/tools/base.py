"""Tool 协议与公共数据结构。

每个工具（无论 builtin/security/personal）都实现 `Tool` 抽象类。
Anthropic SDK 的 tool_use 协议由 ToolWorker 适配。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """工具执行结果。"""

    ok: bool
    output: str
    error: str | None = None
    error_code: str | None = None  # 结构化错误码，供 recovery_node 精确路由
    artifacts: list[dict[str, Any]] = []

    @classmethod
    def fail(cls, error: str, error_code: str = "UNKNOWN", **kw: Any) -> "ToolResult":
        """快捷构造失败结果。"""
        return cls(ok=False, output="", error=error, error_code=error_code, **kw)


class Tool(ABC):
    """所有工具的基类。"""

    name: str
    description: str
    input_schema: dict[str, Any]

    # 工具类别：exec / file / skill / agent / mcp /
    # orchestration / knowledge / runtime。用于按类组织工具说明与前端选择器；
    # 默认 exec，子类按需覆盖。纯元数据，不改变现有行为。
    category: str = "exec"

    # ── 披露策略（tool_search 动态工具披露）─────────────────────────
    # "static"  → 常驻绑定给模型（默认，现有全部内置工具行为不变）。
    # "dynamic" → 藏在 tool_search 之后：不直接绑定，模型需先用 tool_search
    #             按关键词搜索、披露后才会在下一轮被绑定并可调用。
    # 声明式 CLI 工具与 MCP 工具设为 dynamic，抑制 prompt 里的工具定义膨胀。
    disclosure: str = "static"

    # ── HITL 审批门（item 6，可选）─────────────────────────────────
    # requires_approval=True 的工具在执行前需人工审批（由 execute_tool_core 检查，
    # 见 harness/infra/approvals.py）。默认 False：现有工具均不受影响。
    requires_approval: bool = False
    approval_message: str = "确认执行工具 {tool_name}？"
    # 风险等级：审批 UI 的权威风险信号（critical|high|medium|low）。
    # 空串 = 由审批门按 category 派生（见 harness/security/approvals.classify_risk）；
    # 工具可显式覆盖以精确标注（如破坏性操作设 "critical"）。
    risk_level: str = ""

    @abstractmethod
    async def run(self, **kwargs: Any) -> ToolResult: ...

    def approval_context(self, tool_input: dict[str, Any]) -> dict[str, str]:
        """审批展示上下文的工具级提取规则（HITL 卡片的 对象/范围/影响）。

        默认返回空 dict——由审批门（harness/security/approvals）按通用入参键派生
        target、按执行环境派生 scope、按风险等级派生 impact。需要精确描述的工具
        （如主动扫描要区分单主机 vs 网段）可覆盖本方法，返回 target/scope/impact
        任意子集；未提供的键仍走审批门的通用派生。
        """
        return {}

    def to_anthropic(self) -> dict[str, Any]:
        """转成 Anthropic Messages API 的 tools 项格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_langchain(self) -> dict[str, Any]:
        """转成 Anthropic 工具格式 dict，供 ChatAnthropic.bind_tools 使用。

        直接暴露 input_schema，确保 LLM 看到正确的参数定义，
        避免从 **kwargs 函数签名推断出空 schema 导致 LLM 生成错误参数。
        """
        return self.to_anthropic()
