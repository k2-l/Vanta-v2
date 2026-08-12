"""Runtime config overrides — persisted to {data_dir}/config.json.

Values written here take precedence over data/config.toml defaults.
After every write, get_settings.cache_clear() is called so the next
call to get_settings() re-reads both data/config.toml and the JSON layer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _path(data_dir: str) -> Path:
    return Path(data_dir) / "config.json"


def _invalidate_model_cache() -> None:
    """Clear the bound-model and base-model caches in harness.core.graph.models.

    Called explicitly after every config write so the next agent call picks
    up any changed model name, api_key, or max_tokens immediately.
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
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(data_dir: str, updates: dict[str, Any]) -> None:
    """Merge *updates* into the existing override file, then clear settings cache."""
    p = _path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    current = load(data_dir)
    current.update(updates)
    # None values → deletion (fall back to config.toml default)
    current = {k: v for k, v in current.items() if v is not None}
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    # Invalidate lru_cache so next get_settings() sees the new values
    from harness.infra.settings import get_settings
    get_settings.cache_clear()
    # Also clear the bound-model and base-model caches so the next agent call
    # picks up any changed model name, api_key, or max_tokens immediately.
    _invalidate_model_cache()
