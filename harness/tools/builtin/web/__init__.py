"""联网研究工具：WebSearch（搜索）+ WebFetch（读网页）。

都在 harness 进程内直接发出站 HTTP（不走 workspace 沙箱/容器分支），
共用底座在 _net.py（出站 URL 安全校验 + HTML→纯文本）。
"""
