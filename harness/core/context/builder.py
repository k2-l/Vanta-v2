<<<<<<< HEAD
"""
context_builder — 合并 Agent + Skill L1 紧凑清单，生成 system prompt 注入块。

数据源: 纯文件系统
- Agent: {VANTA_ROOT}/workspace/agents/*/AGENT.md
- Skill: {VANTA_ROOT}/workspace/skills/*/SKILL.md

注入 token 上限：MAX_INJECT_TOKENS（默认 3000）。
AgentRegistry/SkillRegistry.as_prompt_block() 已输出紧凑描述，通常不会超限。
token 检查保持为安全网，极低概率触发 name-only 回退。

缓存策略（TTL = 30s）：
  - load_and_build()    — L1 紧凑清单
  - load_dep_context()  — 文件系统模式下无 entity 依赖概念，返回空
  调用 invalidate_context_cache() 可强制失效。
=======
"""L1 清单注入块生成 —— 委托给 EntityProvider（agent + skill）。

数据源: 文件系统（provider 内部扫描 workspace/{agents,skills}/<name>/*.md）。
注入 token 上限 MAX_INJECT_TOKENS（默认 3000）：超限降级为 name-only。
结果缓存 _CACHE_TTL 秒；invalidate_context_cache() 强制失效并重扫 provider 索引。
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
"""

from __future__ import annotations

<<<<<<< HEAD
import os
import time
from pathlib import Path

from harness.core.foundation.tokens import count_tokens
from harness.infra.logging import log
=======
import time

from harness.core.foundation.tokens import count_tokens
from harness.infra.logging import log
from harness.providers import get_provider, reload_all
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)

MAX_INJECT_TOKENS = 3_000
_CACHE_TTL = 30.0

_l1_cache: tuple[str, float] | None = None


def invalidate_context_cache() -> None:
<<<<<<< HEAD
    """清除全部上下文缓存。"""
    global _l1_cache
    _l1_cache = None
    try:
        from harness.skills.loader import invalidate_entries_cache
        invalidate_entries_cache()
=======
    """清除 L1 缓存并重扫 provider 索引（CRUD 写入后调用）。"""
    global _l1_cache
    _l1_cache = None
    try:
        reload_all()
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    except Exception:
        pass


<<<<<<< HEAD
# ═══════════════════════════════════════════════════════════
# 文件系统扫描（内部）
# ═══════════════════════════════════════════════════════════

def _get_vanta_root() -> Path:
    return Path(os.getenv("VANTA_ROOT", str(Path.home() / "Vanta")))


def _list_agents() -> list[dict]:
    """扫描 agents 目录，返回 Agent L1 信息列表"""
    agents_dir = _get_vanta_root() / "workspace" / "agents"
    if not agents_dir.is_dir():
        return []

    agents = []
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_md = agent_dir / "AGENT.md"
        if not agent_md.is_file():
            continue

        try:
            raw = agent_md.read_text(encoding="utf-8")
        except Exception:
            continue

        import re
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', raw, re.DOTALL)
        description = ""
        if match:
            try:
                import yaml
                meta = yaml.safe_load(match.group(1)) or {}
                description = meta.get("description", "")
            except Exception:
                pass

        agents.append({
            "name": agent_dir.name,
            "description": description,
        })

    return agents


def _list_skills() -> list[dict]:
    """扫描 skills 目录，返回 Skill L1 信息列表"""
    from harness.skills.loader import _scan_file_skills

    skills = _scan_file_skills()
    return [
        {
            "name": name,
            "description": skill.description,
            "keywords": skill.keywords,
        }
        for name, skill in skills.items()
    ]


# ═══════════════════════════════════════════════════════════
# L1 prompt 生成
# ═══════════════════════════════════════════════════════════

def _build_agent_l1(name_filter: set[str] | None = None) -> str:
    agents = _list_agents()
    if name_filter:
        agents = [a for a in agents if a["name"] in name_filter]
    if not agents:
        return ""

    lines = ["# 可用 Agent 清单 (Agent L1)\n"]
    for a in agents:
        desc = a["description"][:80] + "..." if len(a["description"]) > 80 else a["description"]
        lines.append(f"- **{a['name']}**: {desc}")
    return "\n".join(lines)


def _build_skill_l1(name_filter: set[str] | None = None) -> str:
    skills = _list_skills()
    if name_filter:
        skills = [s for s in skills if s["name"] in name_filter]
    if not skills:
        return ""

    lines = ["# 可用技能清单 (Skill L1)\n"]
    for s in skills:
        desc = s["description"][:80] + "..." if len(s["description"]) > 80 else s["description"]
        kw_str = f" [触发: {', '.join(s['keywords'][:5])}]" if s["keywords"] else ""
        lines.append(f"- **{s['name']}**: {desc}{kw_str}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 公开接口
# ═══════════════════════════════════════════════════════════

async def load_and_build() -> str:
    """加载 active Agent + Skill 的 L1 清单，token 超限时降级为 name-only。

    结果缓存 _CACHE_TTL 秒。
    """
=======
async def load_and_build() -> str:
    """合并 Agent + Skill 的 L1 清单；token 超限降级为 name-only。结果缓存 _CACHE_TTL 秒。"""
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    global _l1_cache
    now = time.monotonic()
    if _l1_cache is not None and (now - _l1_cache[1]) < _CACHE_TTL:
        return _l1_cache[0]

    try:
<<<<<<< HEAD
        agent_block = _build_agent_l1()
        skill_block = _build_skill_l1()
        full_block = "\n\n".join(b for b in (agent_block, skill_block) if b)

        token_count = count_tokens(full_block)
        if token_count <= MAX_INJECT_TOKENS:
=======
        agent_p = get_provider("agent")
        skill_p = get_provider("skill")
        full_block = "\n\n".join(b for b in (agent_p.list_l1(), skill_p.list_l1()) if b)

        if count_tokens(full_block) <= MAX_INJECT_TOKENS:
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
            result = full_block
        else:
            log.warning(
                "context_builder.token_budget_exceeded",
<<<<<<< HEAD
                tokens=token_count,
                limit=MAX_INJECT_TOKENS,
                fallback="name_only",
            )
            agents = _list_agents()
            skills = _list_skills()
            agent_names = ", ".join(a["name"] for a in agents)
            skill_names = ", ".join(s["name"] for s in skills)
            result = "\n\n".join(
                b for b in (
                    f"# 可用 Agent\n{agent_names}" if agent_names else "",
                    f"# 可用 Skill\n{skill_names}" if skill_names else "",
                ) if b
            )
            if count_tokens(result) > MAX_INJECT_TOKENS:
                result = result[:MAX_INJECT_TOKENS * 3]
    except Exception as exc:
=======
                limit=MAX_INJECT_TOKENS,
                fallback="name_only",
            )
            agent_names = ", ".join(agent_p.names())
            skill_names = ", ".join(skill_p.names())
            result = "\n\n".join(
                b
                for b in (
                    f"# 可用 Agent\n{agent_names}" if agent_names else "",
                    f"# 可用 Skill\n{skill_names}" if skill_names else "",
                )
                if b
            )
            if count_tokens(result) > MAX_INJECT_TOKENS:
                result = result[: MAX_INJECT_TOKENS * 3]
    except Exception as exc:  # noqa: BLE001
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
        log.warning("context_builder.load_failed", exc=str(exc)[:100])
        result = ""

    _l1_cache = (result, now)
    return result


<<<<<<< HEAD
async def load_matched_block(
    matched_skills: set[str] | None = None,
    matched_agents: set[str] | None = None,
) -> str:
    """加载只包含匹配实体的 L1 紧凑清单（用于双层匹配的第二层）。"""
    agent_block = _build_agent_l1(name_filter=matched_agents)
    skill_block = _build_skill_l1(name_filter=matched_skills)
    return "\n\n".join(b for b in (agent_block, skill_block) if b)


async def load_dep_context() -> str:
    """加载 active 实体的依赖树。

    文件系统模式下无 entity 依赖概念，返回空字符串。
    后续如需支持，可从 agents/*/deps.yaml 加载。
    """
=======
async def load_dep_context() -> str:
    """依赖上下文：文件系统模式下无此概念，返回空字符串。"""
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
    return ""
