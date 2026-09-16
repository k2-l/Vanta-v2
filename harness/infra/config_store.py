"""Runtime config overrides — persisted to ignored {data_dir}/config.local.json.

Non-secret values written here take precedence over data/config.toml defaults.
Credential fields are ignored by get_settings() and must come from environment variables.
After every write, get_settings.cache_clear() is called so the next
call to get_settings() re-reads both data/config.toml and the JSON layer.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_PROCESS_LOCK = threading.RLock()


def _path(data_dir: str) -> Path:
    return Path(data_dir) / "config.local.json"


@contextmanager
def _config_lock(path: Path):
    """串行化同进程线程及多个服务进程的 read-modify-write。"""
    lock_path = path.with_name(f".{path.name}.lock")
    with _PROCESS_LOCK, lock_path.open("a+b") as lock_file:
        if os.name == "nt":  # pragma: no cover - CI 使用 POSIX
            import msvcrt

            lock_file.seek(0)
            if not lock_file.read(1):
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _invalidate_model_cache() -> None:
    """Clear the bound-model and base-model caches in harness.core.graph.models.

    Called explicitly after every config write so the next agent call picks
    up any changed model name or token limit immediately.
    If the agent package is not importable (e.g. running in a slim context),
    this is a no-op — but the missing import is surfaced as a warning rather
    than swallowed silently.
    """
    import importlib.util
    if importlib.util.find_spec("harness.core.graph.models") is None:
        import warnings
        warnings.warn(
            "harness.core.graph.models not found; model cache not invalidated",
            ImportWarning,
            stacklevel=2,
        )
        return
    from harness.core.graph.models import clear_model_caches
    clear_model_caches()


def load(data_dir: str) -> dict[str, Any]:
    p = _path(data_dir)
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"运行时配置损坏，拒绝覆盖：{p}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"运行时配置必须是 JSON object：{p}")
    return value


def save(data_dir: str, updates: dict[str, Any]) -> None:
    """Merge *updates* into the existing override file, then clear settings cache."""
    p = _path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _config_lock(p):
        current = load(data_dir)
        current.update(updates)
        # None values → deletion (fall back to config.toml default)
        current = {k: v for k, v in current.items() if v is not None}
        payload = json.dumps(current, indent=2, ensure_ascii=False)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=p.parent,
                prefix=f".{p.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                temp_path = Path(tmp.name)
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_path, p)
            os.chmod(p, 0o600)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    # Invalidate lru_cache so next get_settings() sees the new values
    from harness.infra.settings import get_settings
    get_settings.cache_clear()
    # Also clear the bound-model and base-model caches so the next agent call
    # picks up any changed model name or token limit immediately.
    _invalidate_model_cache()
