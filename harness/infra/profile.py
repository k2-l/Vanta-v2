"""用户 profile 加载 / 模板初始化。

profile.md 是一份用户自己写的"关于我"，会被注入到 Supervisor 的 system prompt。
首次运行不存在则写入默认模板，让用户后续在 TUI / 编辑器里自行修改。
"""

from __future__ import annotations

import time
from pathlib import Path

from harness.infra.settings import get_settings

_PROFILE_TTL = 60.0  # seconds — profile file rarely changes mid-session
_profile_cache: tuple[str, float] | None = None  # (content, monotonic_ts)

DEFAULT_PROFILE = """\
# 关于用户

> 这份文档是 Harness 用来理解你是谁、怎样和你协作的。
> 你可以随时编辑（在 TUI 中输入 `/profile` 会打开提示）。
> 写得越具体，Harness 行为越贴合你的偏好。

## 角色与背景
- 暂未填写。比如：你是谁、做什么、技术栈

## 偏好的协作方式
- 暂未填写。比如：是否喜欢直接给答案、是否需要解释背景、语言偏好

## 长期目标 / 关心的项目
- 暂未填写。比如：当前主项目、研究方向、不希望涉及的领域

## 不要做的事
- 暂未填写。比如：不要默认推送代码、不要给罗列式总结
"""


def ensure_profile() -> Path:
    s = get_settings()
    p = Path(s.profile_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(DEFAULT_PROFILE, encoding="utf-8")
    return p


def load_profile() -> str:
    global _profile_cache
    now = time.monotonic()
    if _profile_cache is not None:
        text, ts = _profile_cache
        if now - ts < _PROFILE_TTL:
            return text
    text = ensure_profile().read_text(encoding="utf-8")
    _profile_cache = (text, now)
    return text


def invalidate_profile_cache() -> None:
    global _profile_cache
    _profile_cache = None
