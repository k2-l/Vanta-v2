"""共享的库目录安全守卫：解析路径、硬拒落在 git 配置路径 data/ 内、建目录(0700)。

secrets_vault 与 output_vault 共用此唯一可审计点，避免守卫重复导致的沉默失效
（将来加固一份漏了另一份，防护会静默失去作用）。
"""

from __future__ import annotations

import os
from pathlib import Path

# git 跟踪的 data/（含被提交的 config）锚定到**源码位置**、不依赖进程 cwd：
# 本文件在 harness/infra/ 下，parents[2] 即仓库根；挪动本文件需同步这个深度。
# 旧写法 Path("data").resolve() 相对 cwd：cwd 非仓库根时会查错 data/、放行本应拒的绝对路径。
_DATA_DIR = (Path(__file__).resolve().parents[2] / "data").resolve()


def guarded_dir(env_var: str, default: str, label: str) -> Path:
    """解析 env_var/default 为绝对路径，硬拒落在 git 配置路径 data/ 内，建目录(0700)后返回。"""
    raw = os.environ.get(env_var, "").strip() or default
    path = Path(raw).expanduser().resolve()
    if path == _DATA_DIR or _DATA_DIR in path.parents:
        raise RuntimeError(f"{label} 不得位于 git 配置路径 data/ 内：{path}")
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path
