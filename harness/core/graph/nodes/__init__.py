"""LangGraph 节点实现。

三层加载架构（L1/L2/L3）：
  L1（system prompt）：name + compact description
    加载方式：preprocess_node → context.builder.load_and_build() / load_matched_block()
    双层匹配：先 embedding 预筛选 + keyword router，再选择性加载匹配项
    Profile 过滤：profile 关键词作为 query augmentation，影响 embedding 排序
    主文件：skills/loader.py / core/agent_loader.py / context/builder.py

  L2（按需加载）：完整 description + triggers + argument_hint
    加载方式：agent 节点调用 load_agent / load_skill 工具
    主文件：harness/tools/builtin/load_skill.py

  L3（级联加载）：content + dependencies chain（EntityResolver）
    加载方式：EntityResolver 自动解析 frontmatter dependencies 字段
    主文件：harness/infra/deps.py / resolver.py

节点列表：
  preprocess  → 装载会话/画像/记忆，检查 token 预算，初始化 Scratchpad
  agent       → 调用 LLM（ChatAnthropic），支持 tool_use 流式输出，记录用量
  tool        → 执行工具调用（并发），写回 ToolMessage
  recovery    → 错误分类 + 5 种恢复策略
  summarize   → Rolling Summary：压缩超窗口的旧消息

模型工厂与缓存（_get_base_model / clear_model_caches）已移至 harness.core.graph.models。
"""

from __future__ import annotations

from .agent import agent_node as agent_node
from .preprocess import preprocess_node as preprocess_node
from .recovery import recovery_node as recovery_node
from .summarize import summarize_node as summarize_node
from .tools import tool_node as tool_node
