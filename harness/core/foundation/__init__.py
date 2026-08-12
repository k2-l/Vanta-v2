"""foundation — Agent 运行时的叶子词汇层（state / errors / events / tokens / registry）。

零包内依赖：任何上层都可安全导入。registry 由 context 下沉至此后，
context.builder ↔ agent_loader 的旧循环依赖被打断。
"""
