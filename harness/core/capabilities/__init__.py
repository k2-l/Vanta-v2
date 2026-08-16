"""capabilities — 可插拔的域能力（与 foundation / context / graph 核心管线层并列）。

<<<<<<< HEAD
  skills.py    技能装载 + 加权路由 + 查询匹配
  agents.py    Agent 定义装载（L1 索引 + 按需加载）
  memory.py    长期记忆
  services.py  会话标题 titler
  utils.py     域间共享：EntityContent（Content 共同字段）/ render_l1_block（L1 清单渲染）

=======
  memory.py    长期记忆
  services.py  会话标题 titler

实体加载（agents / skills）已迁至统一协议
（harness.contracts + harness.agents.provider / harness.skills.provider）。
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
请直接 from harness.core.capabilities.<域> import ...。
"""
