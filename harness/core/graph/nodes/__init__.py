"""LangGraph 节点实现。

渐进式披露（L1/L2/L3，对齐 Claude Code）：
  L1（system prompt）：name + description 清单，恒注入
    加载方式：preprocess_node → context.builder.load_and_build()
    选择：由模型读 description 完成，无关键词 / 向量路由
    主文件：agents/provider.py / skills/provider.py / context/builder.py

  L2（按需加载）：SKILL.md / AGENT.md 正文
    加载方式：agent 节点调用 Skill / load_agent 工具
    主文件：harness/tools/builtin/orchestration/load_skill.py

  L3（渐进加载）：SKILL.md 正文引用的同目录附带文件
    加载方式：模型按需用 Read 工具打开引用路径

节点列表：
  preprocess  → 装载 L1 清单 / 画像 / 记忆，检查 token 预算
  agent       → 调用 LLM（ChatAnthropic），支持 tool_use 流式输出，记录用量
  tool        → 执行工具调用（并发），写回 ToolMessage
  recovery    → 错误分类 + 5 种恢复策略

上下文压缩（Rolling Summary）已从自动流程移除，改为用户主动触发，
不再作为图节点存在（见 core/context/summarize.py + routes/sessions.py）。

模型工厂与缓存（_get_base_model / clear_model_caches）已移至 harness.core.graph.models。
"""

from __future__ import annotations

from .agent import agent_node as agent_node
from .preprocess import preprocess_node as preprocess_node
from .recovery import recovery_node as recovery_node
from .tools import tool_node as tool_node
