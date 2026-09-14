"""BaseFileProvider —— 文件系统实体的通用加载器（实现 EntityProvider 的公共部分）。

子类只需声明 kind / filename / l1_header，并覆写 _full()（字段映射）。
_meta() 对两域一致，已在基类实现，通常无需覆写。
读（reload / list_l1 / get）与写（write / delete）均在基类实现；
写入按模型契约支持的字段序列化（to_frontmatter），未知字段不写入。
"""

from __future__ import annotations

import time
from pathlib import Path

import structlog

from harness.contracts.frontmatter import (
    delete_entity,
    iter_entity_dirs,
    parse_bool,
    split_frontmatter,
    write_entity,
)
from harness.contracts.models import EntityFull, EntityMeta
from harness.contracts.render import compact, render_l1_block

log = structlog.get_logger()


class BaseFileProvider:
    kind: str = ""
    filename: str = ""  # "AGENT.md" | "SKILL.md"
    l1_header: str = "# 可用清单"

    def __init__(self, root: str | Path, *, ttl: float = 30.0):
        self._root = Path(root)
        self._index: dict[str, EntityMeta] = {}  # name -> L1 元数据
        self._dirs: dict[str, Path] = {}  # name -> 实体目录（get 时懒读正文用）
        self._loaded = False
        self._ttl = ttl  # 索引自刷新 TTL（秒）
        self._loaded_at = 0.0

    @property
    def root(self) -> Path:
        return self._root

    # ── 生命周期 ─────────────────────────────────────────────
    def reload(self) -> int:
        """扫描 root，重建内存索引。返回条目数。"""
        index: dict[str, EntityMeta] = {}
        dirs: dict[str, Path] = {}
        for dirname, d, md in iter_entity_dirs(self._root, self.filename):
            try:
                raw = md.read_text(encoding="utf-8")
            except OSError:
                log.warning("provider.read_failed", kind=self.kind, path=str(md))
                continue
            fm, _body = split_frontmatter(raw)
            name = fm.get("name") or dirname
            index[name] = self._meta(fm, name)
            dirs[name] = d
        self._index, self._dirs = index, dirs
        self._loaded = True
        self._loaded_at = time.monotonic()
        log.info("provider.loaded", kind=self.kind, root=str(self._root), count=len(index))
        return len(index)

    def _ensure(self) -> None:
        if not self._loaded or (time.monotonic() - self._loaded_at) >= self._ttl:
            self.reload()

    # ── L1 清单 ──────────────────────────────────────────────
    def list_l1(self, name_filter: set[str] | None = None) -> str:
        """渲染 L1 紧凑清单（模型自动调用目录，排除 disable-model-invocation 项）。"""
        self._ensure()
        entries: dict[str, str] = {}
        for name, meta in self._index.items():
            if meta.disable_model_invocation:
                continue
            if name_filter is not None and name not in name_filter:
                continue
            entries[name] = compact(meta.description)
        return render_l1_block(entries, self.l1_header)

    # ── L2 全文 ──────────────────────────────────────────────
    def get(self, name: str) -> EntityFull | None:
        self._ensure()
        meta = self._index.get(name)
        if meta is None:
            return None
        d = self._dirs[name]
        try:
            raw = (d / self.filename).read_text(encoding="utf-8")
        except OSError:
            log.warning("provider.get_read_failed", kind=self.kind, name=name)
            return None
        fm, body = split_frontmatter(raw)
        return self._full(meta, fm, body.strip(), str(d))

    def has(self, name: str) -> bool:
        self._ensure()
        return name in self._index

    def names(self) -> list[str]:
        """模型可自动调用的实体名（排除 disable-model-invocation）。"""
        self._ensure()
        return [n for n, m in self._index.items() if not m.disable_model_invocation]

    # ── 写（受支持字段；写/删即时更新内存索引） ─────────────
    def all_names(self) -> list[str]:
        """全部实体名（含 disable-model-invocation），管理/CRUD 清单用。"""
        self._ensure()
        return list(self._index)

    def write(self, name: str, full: EntityFull) -> None:
        """按模型契约写实体（to_frontmatter 不序列化未知字段）。"""
        write_entity(self._root, name, self.filename, full)
        if self._loaded:
            self._index[name] = full.meta
            self._dirs[name] = self._root / name

    def delete(self, name: str) -> bool:
        """删除实体目录；不存在返回 False。"""
        if not delete_entity(self._root, name):
            return False
        if self._loaded:
            self._index.pop(name, None)
            self._dirs.pop(name, None)
        return True

    # ── 子类钩子 ─────────────────────────────────────────────
    def _meta(self, fm: dict, name: str) -> EntityMeta:
        """L1 元数据映射（两域一致，对齐 CC 调用控制字段）。"""
        return EntityMeta(
            name=fm.get("name") or name,
            description=fm.get("description", ""),
            disable_model_invocation=parse_bool(fm.get("disable-model-invocation")),
            user_invocable=parse_bool(fm.get("user-invocable"), True),
        )

    def _full(self, meta: EntityMeta, fm: dict, body: str, path: str) -> EntityFull:
        """L2 全文映射（唯一必须覆写的钩子）。"""
        raise NotImplementedError
