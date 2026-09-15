"""graph — LangGraph 接线层：

  - build.py     ：主图组装（build_graph + get_graph）
  - routes.py    ：路由谓词（主图 + 子图）
  - nodes/       ：主图节点（preprocess / agent / tool / recovery / summarize）
  - tool_exec.py ：共享单工具执行内核（主图 + 子图共用）
  - models.py    ：ChatAnthropic 模型工厂 + 缓存（叶子，供主图节点与子图共用）
  - subagent/    ：子 agent 图（context / nodes / build / runtime）

薄壳 __init__：只放 docstring、不 re-export（避免饿汉 init 顶出循环；公共面留 P5）。
请直接 from harness.core.graph.<module> import ...。
"""
