"""agents 领域：按名加载 Agent 全文（统一协议入口）。

AgentContent（旧 EntityContent 双轨）已淘汰——子图直接消费 contracts 的 AgentFull。
加载统一走 AgentProvider（EntityProvider 协议），本域不再有自定义读取逻辑。
"""

from __future__ import annotations

from harness.agents.provider import get_agent_provider
from harness.contracts.models import AgentFull


def load_agent(name: str) -> AgentFull | None:
    """经 AgentProvider（EntityProvider 协议）懒读 L2 全文；不存在返回 None。"""
    return get_agent_provider().get(name)
