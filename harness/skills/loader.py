"""skills 领域：技能加载已迁移到统一协议（SkillProvider / EntityProvider）。

invalidate_entries_cache 保留供既有 routes 调用，现为协议实现（reload_all 重扫）。
routes 接入 provider 读写后可删除本模块。
"""

from __future__ import annotations


def invalidate_entries_cache() -> None:
    """协议实现：重扫 agent + skill 索引（reload_all）。

    既有 routes 同时还会调用 invalidate_context_cache()（内部同样 reload_all），
    双调用仅多一次目录扫描，无副作用。
    """
    from harness.providers import reload_all

    reload_all()
