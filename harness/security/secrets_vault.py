"""engagement 凭据的 Fernet 加密存储，路径独立于 git 配置。

⚠️ 本项目有把含活凭据的 data/config 提交进私有仓库的做法；engagement 凭据(Shodan/Censys
key、目标凭据、SSH key)绝不能走那条路径。故默认存仓库外 ~/.vanta/secrets
(HARNESS_SECRETS_DIR 覆盖)、硬拒落在 data/；路径只走 env（不进 git-tracked 的 config）。
主密钥来自 HARNESS_VAULT_KEY，或首用时在 secrets_dir 生成 vault.key(0600)；
每 engagement 一个加密文件 eng-<id>.enc，便于 teardown 清除。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from harness.infra.logging import log
from harness.security.vault_paths import guarded_dir

_DEFAULT_DIR = "~/.vanta/secrets"


def _secrets_dir() -> Path:
    """密钥库目录（仓库外、硬拒 data/、0700）。"""
    return guarded_dir("HARNESS_SECRETS_DIR", _DEFAULT_DIR, "secrets_dir")


def _get_key() -> bytes:
    """取主密钥：env 优先，否则读 / 生成 secrets_dir/vault.key(0600)。"""
    env = os.environ.get("HARNESS_VAULT_KEY", "").strip()
    if env:
        return env.encode()
    key_file = _secrets_dir() / "vault.key"
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    os.chmod(key_file, 0o600)
    log.info("secrets_vault.key_generated", path=str(key_file))
    return key


def _vault_path(engagement_id: str) -> Path:
    return _secrets_dir() / f"eng-{engagement_id}.enc"


def _load(engagement_id: str) -> dict[str, str]:
    """解密读回某 engagement 的凭据 dict；不存在 / 失败返回 {}。"""
    p = _vault_path(engagement_id)
    if not p.exists():
        return {}
    try:
        raw = Fernet(_get_key()).decrypt(p.read_bytes())
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (InvalidToken, ValueError) as exc:
        log.warning("secrets_vault.decrypt_failed", engagement=engagement_id, exc=str(exc)[:120])
        return {}


def _save(engagement_id: str, secrets: dict[str, str]) -> None:
    """加密写回某 engagement 的凭据 dict。"""
    p = _vault_path(engagement_id)
    token = Fernet(_get_key()).encrypt(json.dumps(secrets).encode("utf-8"))
    p.write_bytes(token)
    os.chmod(p, 0o600)


def set_secret(engagement_id: str, name: str, value: str) -> None:
    """写入/更新一条 engagement 凭据（加密落盘）。"""
    secrets = _load(engagement_id)
    secrets[name] = value
    _save(engagement_id, secrets)


def get_secret(engagement_id: str, name: str) -> str | None:
    """取一条凭据明文；不存在返回 None。"""
    return _load(engagement_id).get(name)


def list_secret_names(engagement_id: str) -> list[str]:
    """列出某 engagement 已存凭据的名称（不含值）。"""
    return sorted(_load(engagement_id).keys())


def delete_engagement_secrets(engagement_id: str) -> bool:
    """删除某 engagement 的整个密钥文件（engagement 收尾 / 急停用）。"""
    p = _vault_path(engagement_id)
    if p.exists():
        p.unlink()
        return True
    return False
