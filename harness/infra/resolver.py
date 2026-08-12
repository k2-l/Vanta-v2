"""EntityResolver — 传递性依赖解析、环检测、lazy 策略。

Step 2A 引擎核心。在注册时解析依赖链，检测传递性循环（A→B→A），
支持 load_strategy: lazy（仅注入名称，比 summary 更轻量）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from harness.infra.db import get_dependencies
from harness.infra.logging import log

__all__ = ["DependencyInput", "ResolveResult", "EntityResolver", "format_deps_tree"]


# dep_kind → 被依赖方在 entity_dependencies 中的 source_type
_DEP_KIND_TO_SOURCE_TYPE: dict[str, str] = {
    "inagent": "agent",
    "inskill": "skill",
    "inrepository": "knowledge",
    "inscript": "script",
    "intemplate": "template",
}


def _get_model_for_type(source_type: str):
    """将 source_type 映射到对应的 ORM 模型类；未知类型返回 None。"""
    if source_type == "skill":
        from harness.infra.db import SkillRecord
        return SkillRecord
    if source_type == "agent":
        from harness.infra.db import AgentRecord
        return AgentRecord
    if source_type == "script":
        from harness.infra.db import ScriptRecord
        return ScriptRecord
    if source_type == "template":
        from harness.infra.db import TemplateRecord
        return TemplateRecord
    return None


@dataclass
class DependencyInput:
    """单个依赖条的标准化输入。"""

    dep_kind: str       # "inagent" | "inskill" | "inrepository"
    dep_name: str       # 被依赖方名称
    load_strategy: str = "summary"   # "summary" | "lazy"
    max_depth: int = 3               # 该依赖的递归深度


@dataclass
class ResolveResult:
    """依赖解析结果。

    resolved — 通过解析、可安全写入 entity_dependencies 的依赖列表
    cycles   — 发现的环路径，如 [["agent:A", "skill:B", "agent:A"]]
    truncated — 超 max_depth 截断的实体名
    warnings  — 其他警告（如空 dep_name、未知 dep_kind）
    """

    resolved: list[DependencyInput] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class EntityResolver:
    """依赖解析器 — 构建依赖 DAG、检测传递性循环。

    两个独立的数据结构用于图遍历：
    - ``_path_set``: 当前递归路径上的 (source_type, source_name) 集合，用于环检测
    - ``_visited``:  全局已处理 (source_type, source_name) 集合，用于防重复遍历（菱形依赖保护）

    两者缺一不可：只用 path_set 会重复处理 DAG 的公共子节点（菱形依赖），
    只用 visited 会因为不同路径而无法发现环。
    """

    def __init__(self, db) -> None:
        self.db = db
        self._path_set: set[tuple[str, str]] = set()
        self._visited: set[tuple[str, str]] = set()

    async def resolve(
        self,
        deps: list[DependencyInput],
        source_type: str,
        source_name: str,
    ) -> ResolveResult:
        """递归解析依赖列表，返回通过/过滤结果。

        参数：
          deps:         待解析的依赖列表（通常来自 frontmatter）
          source_type:  依赖方类型（"skill" | "agent"）
          source_name:  依赖方名称

        返回：
          ResolveResult:
            .resolved  — 通过环检测的依赖（可供 update_dependencies 写入）
            .cycles    — 发现的环路径
            .truncated — 超 max_depth 截断的实体名
            .warnings  — 其他警告
        """
        result = ResolveResult()

        if not deps:
            return result

        # 将源实体加入路径集，用于检测 A→B→…→A 的环
        source_key = (source_type, source_name)
        self._path_set.add(source_key)

        for dep in deps:
            if dep.dep_kind in ("inrepository", "inscript", "intemplate"):
                result.resolved.append(dep)
                continue

            if dep.dep_kind not in ("inskill", "inagent"):
                result.warnings.append(f"unknown dep_kind: {dep.dep_kind}")
                continue

            if not dep.dep_name:
                result.warnings.append(f"empty dep_name for {dep.dep_kind}")
                continue

            target_type = _DEP_KIND_TO_SOURCE_TYPE[dep.dep_kind]
            target_key = (target_type, dep.dep_name)

            # 当前路径上已存在 → 该 dep 本身形成环
            if target_key in self._path_set:
                cycle = [f"{source_type}:{source_name}", f"{target_type}:{dep.dep_name}"]
                result.cycles.append(cycle)
                result.warnings.append(f"self-cycle dep skipped: {' → '.join(cycle)}")
                log.warning("resolver.cycle_skipped", cycle=" → ".join(cycle))
                continue

            # 已处理过且无环 → 直接通过
            if target_key in self._visited:
                result.resolved.append(dep)
                continue

            # DFS 追踪传递链
            cycle_path = await self._trace_dfs(
                target_type=target_type,
                target_name=dep.dep_name,
                max_depth=dep.max_depth,
                _depth=0,
                _path_prefix=f"{target_type}:{dep.dep_name}",
            )
            if cycle_path:
                full_cycle = [f"{source_type}:{source_name}"] + cycle_path
                result.cycles.append(full_cycle)
                result.warnings.append(f"transitive cycle dep skipped: {' → '.join(full_cycle)}")
                log.warning("resolver.transitive_cycle", cycle=" → ".join(full_cycle))
            else:
                result.resolved.append(dep)

        self._path_set.discard(source_key)
        return result

    async def _trace_dfs(
        self,
        target_type: str,
        target_name: str,
        max_depth: int,
        _depth: int,
        _path_prefix: str,
    ) -> list[str] | None:
        """DFS 遍历依赖链。返回环路径字符串列表，无环则返回 None。"""
        key = (target_type, target_name)

        if key in self._path_set:
            return [f"{target_type}:{target_name}"]

        if key in self._visited:
            return None

        if _depth >= max_depth:
            log.info("resolver.truncated", entity=_path_prefix, depth=_depth)
            return None

        self._path_set.add(key)
        self._visited.add(key)

        sub_deps = await self._fetch_entity_deps(target_type, target_name)

        for sub in sub_deps:
            sub_target = _DEP_KIND_TO_SOURCE_TYPE.get(sub.dep_kind)
            if sub_target is None or sub_target in ("knowledge", "script", "template"):
                continue  # leaf entities 不递归
            cycle = await self._trace_dfs(
                target_type=sub_target,
                target_name=sub.dep_name,
                max_depth=max_depth,
                _depth=_depth + 1,
                _path_prefix=f"{_path_prefix} → {sub_target}:{sub.dep_name}",
            )
            if cycle:
                self._path_set.discard(key)
                return [f"{target_type}:{target_name}"] + cycle

        self._path_set.discard(key)
        return None

    async def _fetch_entity_deps(
        self, source_type: str, source_name: str
    ) -> list:
        """通过 (source_type, source_name) 查询实体的现有依赖。

        先用名称查实体 ID → 再用 ID 查 entity_dependencies。
        """
        entity_id = await self._name_to_id(source_type, source_name)
        if entity_id is None:
            return []
        return await get_dependencies(self.db, source_type, entity_id)

    async def _name_to_id(self, source_type: str, source_name: str) -> str | None:
        """将 (source_type, source_name) 解析为实体 UUID。"""
        from sqlalchemy import select

        M = _get_model_for_type(source_type)
        if M is None:
            return None
        row = await self.db.execute(
            select(M.id).where(M.name == source_name)  # type: ignore[arg-type]
        )
        return row.scalar_one_or_none()


# ─── 依赖树格式化（Step 2B） ─────────────────────────────────────────

async def _name_to_id_db(db, source_type: str, source_name: str) -> str | None:
    """将 (source_type, source_name) 解析为实体 UUID（模块级辅助，供树格式化使用）。"""
    from sqlalchemy import select

    M = _get_model_for_type(source_type)
    if M is None:
        return None
    row = await db.execute(select(M.id).where(M.name == source_name))  # type: ignore[arg-type]
    return row.scalar_one_or_none()


async def _format_deps_tree_lines(
    db,
    source_type: str,
    source_id: str,
    max_depth: int,
    _depth: int,
    _prefix: str,
) -> list[str]:
    """递归构建树形行列表。"""
    deps = await get_dependencies(db, source_type, source_id)
    if _depth > max_depth:
        return [f"{_prefix}└ ... (子树因深度限制未展示)"]
    if not deps:
        return []

    lines: list[str] = []
    for i, dep in enumerate(deps):
        is_last = i == len(deps) - 1
        label = dep.dep_name if dep.load_strategy == "lazy" else f"{dep.dep_kind}:{dep.dep_name}"

        connector = "└ " if is_last else "├ "
        continuation = "  " if is_last else "│ "

        if _depth == 0:
            child_prefix = continuation
        else:
            child_prefix = _prefix + continuation

        # 检查依赖目标是否存在及 active 状态
        dep_id = None
        is_inactive = False
        target_type = _DEP_KIND_TO_SOURCE_TYPE.get(dep.dep_kind)
        if target_type and target_type not in ("knowledge",):
            dep_id = await _name_to_id_db(db, target_type, dep.dep_name)
            if dep_id is None:
                label += " [已不存在]"
            else:
                # 内联 active 状态检查
                from sqlalchemy import select as _select
                M = _get_model_for_type(target_type)
                if M is not None:
                    _row = await db.execute(_select(M.active).where(M.id == dep_id))
                    is_inactive = not bool(_row.scalar_one_or_none())
                if is_inactive:
                    label += " [已停用]"

        # 渲染当前行
        if _depth == 0:
            lines.append(f"{connector}{label}")
        else:
            lines.append(f"{_prefix}{connector}{label}")

        # 递归展示子依赖（仅对存在且 active 的实体）
        if dep_id and not is_inactive:
            child_lines = await _format_deps_tree_lines(
                db, target_type, dep_id,
                max_depth, _depth + 1, child_prefix,
            )
            lines.extend(child_lines)

    return lines


async def format_deps_tree(
    db,
    source_type: str,
    source_id: str,
    max_depth: int = 3,
) -> str:
    """以树形格式展示实体的依赖链。

    输出示例：:

      ├ inskill:java-audit
      │ └ inrepository:semgrep-rules
      └ inrepository:fastjson

    树形工整对齐，支持 summary/lazy 两种标签格式。
    传递性依赖通过 max_depth 截断（环已在注册时由 EntityResolver 过滤）。
    """
    if not db:
        return ""
    lines = await _format_deps_tree_lines(
        db, source_type, source_id, max_depth, 0, "",
    )
    return "\n".join(lines)
