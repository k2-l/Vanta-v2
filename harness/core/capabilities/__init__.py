"""capabilities — 可插拔的域能力（与 foundation / context / graph 核心管线层并列）。

  skills.py    技能装载 + 加权路由 + 查询匹配
  agents.py    Agent 定义装载（L1 索引 + 按需加载）
  memory.py    长期记忆
  services.py  会话标题 titler
  utils.py     域间共享：EntityContent（Content 共同字段）/ render_l1_block（L1 清单渲染）

请直接 from harness.core.capabilities.<域> import ...。
"""
