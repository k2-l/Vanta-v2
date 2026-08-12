"""加密存储工具输出，替代明文 .tool_outputs/。

复用密钥库主密钥加密落盘，按 engagement 归档、带 TTL 留存，收尾 / 急停时清除。
默认存仓库外 ~/.vanta/outputs（HARNESS_OUTPUTS_DIR 覆盖），硬拒落在 data/。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from harness.infra.logging import log
from harness.security.secrets_vault import _get_key
from harness.security.vault_paths import guarded_dir

_DEFAULT_DIR = "~/.vanta/outputs"


def _outputs_dir() -> Path:
    """输出库目录（仓库外、拒 data/、0700）。"""
    return guarded_dir("HARNESS_OUTPUTS_DIR", _DEFAULT_DIR, "outputs_dir")


def store_output(engagement_id: str, tool_name: str, content: str) -> str:
    """加密落盘一段工具输出，返回引用（文件名）。"""
    safe_tool = "".join(c if c.isalnum() else "-" for c in tool_name)[:32] or "tool"
    ref = f"eng-{engagement_id}-{safe_tool}-{int(time.time())}-{os.urandom(4).hex()}.enc"
    token = Fernet(_get_key()).encrypt(content.encode("utf-8"))
    p = _outputs_dir() / ref
    p.write_bytes(token)
    os.chmod(p, 0o600)
    return ref


def read_output(ref: str) -> str | None:
    """解密读回一段输出；不存在/解密失败返回 None。"""
    p = _outputs_dir() / ref
    if not p.exists():
        return None
    try:
        return Fernet(_get_key()).decrypt(p.read_bytes()).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        log.warning("output_vault.decrypt_failed", ref=ref, exc=str(exc)[:120])
        return None


def purge_engagement_outputs(engagement_id: str) -> int:
    """删除某 engagement 的全部输出（收尾/急停用）。返回删除数。"""
    n = 0
    for p in _outputs_dir().glob(f"eng-{engagement_id}-*.enc"):
        p.unlink()
        n += 1
    return n


def purge_expired(ttl_seconds: int) -> int:
    """按留存期删除超过 TTL 的输出。返回删除数。"""
    cutoff = time.time() - ttl_seconds
    n = 0
    for p in _outputs_dir().glob("*.enc"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:  # noqa: PERF203
            pass
    return n
