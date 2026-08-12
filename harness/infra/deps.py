"""实体依赖管理 — frontmatter 解析 + entity_dependencies CRUD。

依赖在 agent/skill 的 YAML frontmatter 中声明：
```yaml
dependencies:
  - inagent: disclosure-reporter
  - inskill: java-audit
  - inrepository: fastjson
```

注册时系统将依赖写入 entity_dependencies 表，
加载 active 实体时注入依赖摘要到 system prompt。
LLM 按需通过 load_agent / load_skill / get_knowledge 取全文。
"""

from __future__ import annotations

from harness.infra.db import EntityDependency, get_dependencies, get_dependents, new_id
from harness.infra.logging import log
from harness.infra.resolver import DependencyInput, EntityResolver, ResolveResult

VALID_DEP_KINDS: frozenset[str] = frozenset({
    "inagent", "inskill", "inrepository", "inscript", "intemplate",
})

# 合法依赖方向矩阵
# "allow" → 通过  "warn" → 通过但记录警告  None → 非法（不计入 resolved）
_ALLOWED_DEP_DIRECTIONS: dict[tuple[str, str], str] = {
    ("agent",  "inagent"):      "allow",
    ("agent",  "inskill"):      "allow",
    ("agent",  "inrepository"): "allow",
    ("skill",  "inskill"):      "allow",
    ("skill",  "inrepository"): "allow",
    ("skill",  "inagent"):      "warn",
    ("agent",  "inscript"):     "allow",
    ("agent",  "intemplate"):   "allow",
    ("skill",  "inscript"):     "allow",
    ("skill",  "intemplate"):   "allow",
}


def validate_dep_directions(
    source_type: str, deps: list[DependencyInput]
) -> tuple[list[DependencyInput], list[str]]:
    """校验依赖方向合法性。返回 (过滤后依赖列表, 警告列表)。
    skill → agent 给出警告；其他非法方向会从 deps 中过滤。
    """
    warnings: list[str] = []
    filtered: list[DependencyInput] = []
    for dep in deps:
        action = _ALLOWED_DEP_DIRECTIONS.get((source_type, dep.dep_kind))
        if action == "warn":
            # "warn" = include the dep but surface a warning to the caller
            warnings.append(
                f"{source_type} 声明 {dep.dep_kind}:{dep.dep_name} "
                f"是不推荐的依赖方向"
            )
            filtered.append(dep)
        elif action is None:
            # None = block silently (dep is dropped; caller sees a warning message only)
            warnings.append(
                f"非法依赖方向: {source_type} → {dep.dep_kind}:{dep.dep_name}"
            )
            # 不加入 filtered，静默过滤
        else:
            filtered.append(dep)
    return filtered, warnings


def parse_dependencies(fm: dict) -> list[DependencyInput]:
    """从已解析的 frontmatter dict 中提取依赖列表。

    parse_frontmatter() 将
      dependencies:
        - inskill: java-audit
        - inrepository: fastjson
    解析为 fm["dependencies"] = ["inskill: java-audit", "inrepository: fastjson"]

    此函数标准化为：
    [DependencyInput(dep_kind="inskill", dep_name="java-audit"), ...]

    格式非法或 dep_kind 不合法时静默跳过该条目，不阻塞注册。
    Step 2A 中所有条目的 load_strategy="summary"、max_depth=3，
    前端支持对象格式后可自定义。
    """
    raw = fm.get("dependencies")
    if not raw or not isinstance(raw, list):
        return []

    result: list[DependencyInput] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        parts = item.split(":", 1)
        if len(parts) != 2:
            continue
        kind = parts[0].strip()
        name = parts[1].strip()
        if kind not in VALID_DEP_KINDS or not name:
            continue
        result.append(DependencyInput(dep_kind=kind, dep_name=name))
    return result


def filter_self_refs(
    source_type: str, entity_name: str, deps: list[DependencyInput]
) -> list[DependencyInput]:
    """过滤直接自引用依赖（skill 引用自身、agent 引用自身），记录 warning。

    返回过滤后的列表（不含自引用条目）。
    """
    filtered: list[DependencyInput] = []
    for dep in deps:
        is_self_ref = (
            (dep.dep_kind == "inskill" and source_type == "skill")
            or (dep.dep_kind == "inagent" and source_type == "agent")
        ) and dep.dep_name == entity_name
        if is_self_ref:
            log.warning(
                "deps.self_reference_skipped",
                entity=entity_name,
                type=source_type,
                dep_kind=dep.dep_kind,
            )
        else:
            filtered.append(dep)
    return filtered


async def resolve_and_filter(
    db,
    source_type: str,
    source_name: str,
    deps: list[DependencyInput],
    resolver: EntityResolver | None = None,
) -> ResolveResult:
    """整合函数：自引用过滤 + 方向校验 + 传递性环检测。

    先执行 filter_self_refs，再执行 validate_dep_directions，
    最后将结果传给 EntityResolver.resolve()。

    resolver: 可传入共享 EntityResolver 实例以保持 _visited 状态（用于级联）。
    """
    deps = filter_self_refs(source_type, source_name, deps)
    deps, direction_warnings = validate_dep_directions(source_type, deps)
    resolver = resolver or EntityResolver(db)
    result = await resolver.resolve(deps, source_type, source_name)
    result.warnings = direction_warnings + result.warnings
    return result


async def update_dependencies(
    db,
    source_type: str,
    source_id: str,
    source_name: str,
    deps: list[DependencyInput],
) -> None:
    """清空实体的旧依赖并写入新依赖。在同一事务内执行。"""
    from sqlalchemy import delete

    await db.execute(
        delete(EntityDependency).where(
            EntityDependency.source_type == source_type,
            EntityDependency.source_id == source_id,
        )
    )
    for dep in deps:
        db.add(EntityDependency(
            id=new_id(),
            source_type=source_type,
            source_id=source_id,
            source_name=source_name,
            dep_kind=dep.dep_kind,
            dep_name=dep.dep_name,
            load_strategy=dep.load_strategy,
            max_depth=dep.max_depth,
        ))


async def cascade_reresolve(
    db,
    source_type: str,
    source_name: str,
    _visited: set[str] | None = None,
    _resolver: EntityResolver | None = None,
) -> list[str]:
    """当某实体的依赖链变更时，重新解析所有依赖该实体的实体。

    递归级联（DAG 遍历，_visited 防环），返回所有被重新解析的实体名称列表。
    整个级联共享同一个 EntityResolver 实例，确保 _visited/_path_set 在递归中一致。
    在 `update_dependencies` 提交后调用。
    """
    if _visited is None:
        _visited = set()
    if _resolver is None:
        _resolver = EntityResolver(db)

    key = f"{source_type}:{source_name}"
    if key in _visited:
        return []
    _visited.add(key)

    dep_kind = f"in{source_type}"
    dependents = await get_dependents(db, dep_kind, source_name)

    re_resolved: list[str] = []
    for dep in dependents:
        try:
            current_deps = await get_dependencies(db, dep.source_type, dep.source_id)
            deps_input = [
                DependencyInput(d.dep_kind, d.dep_name, d.load_strategy, d.max_depth)
                for d in current_deps
            ]
            if not deps_input:
                continue

            result = await resolve_and_filter(db, dep.source_type, dep.source_name, deps_input, resolver=_resolver)
            if result.resolved:
                await update_dependencies(
                    db, dep.source_type, dep.source_id, dep.source_name, result.resolved,
                )

            re_resolved.append(f"{dep.source_type}:{dep.source_name}")

            # 递归级联到下一层（传递共享 resolver）
            nested = await cascade_reresolve(db, dep.source_type, dep.source_name, _visited, _resolver)
            re_resolved.extend(nested)
        except Exception as exc:
            log.warning("cascade_reresolve.failed",
                         entity=f"{dep.source_type}:{dep.source_name}",
                         exc=str(exc)[:100])

    return re_resolved


