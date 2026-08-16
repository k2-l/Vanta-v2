<<<<<<< HEAD
"""
纯文件系统驱动，Claude Code 格式
数据源: {VANTA_ROOT}/workspace/skills/*/SKILL.md
=======
"""skills 领域：技能加载已迁移到统一协议（SkillProvider / EntityProvider）。

invalidate_entries_cache 保留供既有 routes 调用，现为协议实现（reload_all 重扫）。
routes 接入 provider 读写后可删除本模块。
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
"""

from __future__ import annotations

<<<<<<< HEAD
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import structlog
from harness.core.capabilities.utils import render_l1_block

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
# 文件系统 Skill 模型
# ═══════════════════════════════════════════════════════════


@dataclass
class FileSkill:
    name: str
    description: str
    content: str
    keywords: list[str]
    patterns: list[str]
    allowed_tools: list[str]
    model: str | None
    argument_hint: str | None
    path: str


# ═══════════════════════════════════════════════════════════
# SKILL.md 解析
# ═══════════════════════════════════════════════════════════


def _get_skills_root() -> Path:
    vanta_root = os.getenv("VANTA_ROOT", str(Path.home() / "Vanta"))
    return Path(vanta_root) / "workspace" / "skills"


def _parse_skill_md(raw: str) -> tuple[dict, str]:
    """解析 SKILL.md 的 YAML front matter"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", raw, re.DOTALL)
    if not match:
        return {}, raw

    try:
        import yaml

        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}

    return meta, raw[match.end():]


def _extract_keywords(description: str, body: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    for w in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]{3,}", description):
        lower = w.lower()
        if lower not in seen:
            seen.add(lower)
            keywords.append(w)

    trigger_match = re.search(
        r"(?:触发条件|触发时机|When\s+to\s+use|适用场景).*?\n(.*?)(?=\n##|\Z)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if trigger_match:
        for phrase in re.findall(r'["""]([^"""]+)["""]', trigger_match.group(1)):
            if phrase.lower() not in seen:
                seen.add(phrase.lower())
                keywords.append(phrase)

    return keywords[:15]


def _extract_patterns(body: str) -> list[str]:
    match = re.search(
        r"(?:触发条件|触发时机|When\s+to\s+use|适用场景).*?\n(.*?)(?=\n##|\Z)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []

    text = match.group(1)
    return re.findall(r'["""]([^"""]+)["""]', text) + re.findall(r"`([^`]+)`", text)


def _scan_file_skills() -> dict[str, FileSkill]:
    skills_root = _get_skills_root()
    if not skills_root.is_dir():
        log.warning("Skills 根目录不存在", path=str(skills_root))
        return {}

    skills: dict[str, FileSkill] = {}
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        try:
            raw = skill_md.read_text(encoding="utf-8")
        except Exception:
            log.warning("读取 SKILL.md 失败", path=str(skill_md))
            continue

        meta, body = _parse_skill_md(raw)

        name = meta.get("name", skill_dir.name)
        description = meta.get("description", "")
        keywords = _extract_keywords(description, body)
        patterns = _extract_patterns(body)

        skills[name] = FileSkill(
            name=name,
            description=description,
            content=body.strip(),
            keywords=keywords,
            patterns=patterns,
            allowed_tools=meta.get("allowed-tools", []),
            model=meta.get("model"),
            argument_hint=meta.get("argument-hint"),
            path=str(skill_dir),
        )

    log.info("Skills 加载完成", path=str(skills_root), count=len(skills))
    return skills


# ═══════════════════════════════════════════════════════════
# 缓存
# ═══════════════════════════════════════════════════════════

_ENTRIES_CACHE_TTL = 30.0
_entries_cache: tuple[list[dict], float] | None = None


def invalidate_entries_cache() -> None:
    global _entries_cache
    _entries_cache = None


def _get_entries() -> list[dict]:
    global _entries_cache
    now = time.monotonic()
    if _entries_cache is not None and (now - _entries_cache[1]) < _ENTRIES_CACHE_TTL:
        return _entries_cache[0]

    entries: list[dict] = []
    for name, skill in _scan_file_skills().items():
        entries.append(
            {
                "name": name,
                "description": skill.description,
                "keywords": skill.keywords,
                "patterns": skill.patterns,
                "contexts": [],
                "priority": 0,
            }
        )

    _entries_cache = (entries, now)
    return entries


# ═══════════════════════════════════════════════════════════
# 评分函数
# ═══════════════════════════════════════════════════════════

SCORE_THRESHOLD = 0.3
W_KEYWORD = 0.3
W_REGEX = 0.4
W_CONTEXT = 0.3


def _keyword_score(query_lower: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw and kw.lower() in query_lower)
    return hits / len(keywords)


def _regex_score(query: str, patterns: list[str]) -> float:
    if not patterns:
        return 0.0
    for pat in patterns:
        if not pat:
            continue
        try:
            if re.search(pat, query, re.IGNORECASE):
                return 1.0
        except re.error:
            continue
    return 0.0


def _context_score(detected: set[str] | None, contexts: list[str]) -> float:
    if not contexts or not detected:
        return 0.0
    ctx_set = {c.lower() for c in contexts}
    detected_lower = {d.lower() for d in detected}
    inter = ctx_set & detected_lower
    return len(inter) / len(ctx_set)


def _tfidf_fallback(query: str, entries: list[dict]) -> list[str]:
    if not entries or not query.strip():
        return []
    if not _SKLEARN_AVAILABLE:
        return []

    corpus = [" ".join([e["name"], e["description"], " ".join(e["keywords"])]) for e in entries]
    try:
        vec = TfidfVectorizer(lowercase=True, analyzer="char_wb", ngram_range=(2, 4))
        matrix = vec.fit_transform(corpus + [query])
        sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
        best_idx = int(sims.argmax())
        if sims[best_idx] <= 0.0:
            return []
        return [entries[best_idx]["name"]]
    except ValueError:
        return []


def _query_matches_skill(query: str, skill_name: str, keywords: list[str]) -> bool:
    q = query.lower()
    if skill_name:
        name_l = skill_name.lower()
        if name_l in q:
            return True
        for token in re.split(r"[-_/\s]+", name_l):
            if len(token) >= 3 and token in q:
                return True
    return any(kw and kw.lower() in q for kw in keywords)


# ═══════════════════════════════════════════════════════════
# 公开接口
# ═══════════════════════════════════════════════════════════


def get_cached_skill_keywords(name: str) -> list[str]:
    global _entries_cache
    if _entries_cache is None:
        return []
    entries, ts = _entries_cache
    if time.monotonic() - ts >= _ENTRIES_CACHE_TTL:
        return []
    for e in entries:
        if e["name"] == name:
            return e["keywords"]
    return []


async def _do_skill_routing(
    user_query: str,
    active_skill: str | None,
) -> tuple[set[str], str | None]:
    if active_skill:
        keywords = get_cached_skill_keywords(active_skill)
        if _query_matches_skill(user_query, active_skill, keywords):
            return {active_skill}, active_skill

    entries = _get_entries()
    if not entries:
        return set(), None

    q_lower = user_query.lower()
    scored: list[tuple[float, int, str]] = []

    for e in entries:
        ks = _keyword_score(q_lower, e["keywords"])
        rs = _regex_score(user_query, e["patterns"])
        cs = _context_score(None, e["contexts"])
        score = ks * W_KEYWORD + rs * W_REGEX + cs * W_CONTEXT
        if score >= SCORE_THRESHOLD:
            scored.append((score, e["priority"], e["name"]))

    if scored:
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return set(name for _, _, name in scored), scored[0][2]

    fallback = _tfidf_fallback(user_query, entries)
    if fallback:
        return set(fallback), fallback[0]

    return set(), None


def _extract_profile_keywords(profile: str) -> list[str]:
    if not profile:
        return []
    profile_keywords: list[str] = []
    for w in profile.replace("\n", " ").split():
        if len(w) > 2 and (w[0].isupper() or w[0].islower()):
            clean = w.strip(",.!?;:#$%^&*()[]{}\"'").strip()
            if clean and len(clean) > 2:
                profile_keywords.append(clean)
    return list(dict.fromkeys(profile_keywords))[:10]


def _merge_skill_scores(
    router_hits_set: set[str],
    embed_hits: list[dict],
    embed_hits_profile: list[dict],
) -> tuple[set[str], dict[str, float]]:
    matched_skills: set[str] = set()
    score_map: dict[str, float] = {}

    for name in router_hits_set:
        matched_skills.add(name)
        score_map[name] = score_map.get(name, 0) + 0.0

    for h in embed_hits:
        distance = h.get("distance", 1)
        if distance < 0.85:
            matched_skills.add(h["name"])
            score_map[h["name"]] = min(score_map.get(h["name"], 1), distance)

    for h in embed_hits_profile:
        distance = h.get("distance", 1)
        if distance < 0.85:
            name = h["name"]
            matched_skills.add(name)
            boosted = distance * 0.85
            if name not in score_map or boosted < score_map[name]:
                score_map[name] = boosted

    return matched_skills, score_map


def _build_scratchpad(
    score_map: dict[str, float],
    profile_keywords: list[str],
) -> str:
    ranked = sorted(score_map.items(), key=lambda x: x[1])
    parts: list[str] = []
    if ranked:
        parts.append("匹配技能（按相关度排序）：" + "、".join(name for name, _ in ranked))
    if profile_keywords:
        parts.append("Profile 关键词：" + " ".join(profile_keywords[:5]))
    return f"【预筛选】{'；'.join(parts)}\n" if parts else ""


# ═══════════════════════════════════════════════════════════
# ✨ 新增：L1 清单渲染
# ═══════════════════════════════════════════════════════════


def get_skills_l1_prompt(name_filter: set[str] | None = None, with_keywords: bool = True) -> str:
    """
    生成 Skills 的 L1 紧凑清单，用于注入 System Prompt。

    Args:
        name_filter: 只输出指定名称的 Skill；None 输出全部
        with_keywords: 是否在清单中包含关键词标签

    Returns:
        Markdown 格式的 Skill 清单
    """
    skills = _scan_file_skills()
    if not skills:
        return ""

    # 构建符合 render_l1_block 的索引格式
    index = {}
    for name, skill in skills.items():
        # 截取前 100 字符作为 compact 描述
        compact = skill.description[:100]
        if len(skill.description) > 100:
            compact += "..."
        
        index[name] = {
            "compact": compact or "无描述",
            "keywords": skill.keywords,
        }

    return render_l1_block(
        index,
        "# 可用 Skill 清单（Skill L1）",
        name_filter,
        with_keywords=with_keywords,
    )


def get_skill_full_content(name: str) -> str | None:
    """获取指定 Skill 的完整内容（L2）"""
    skills = _scan_file_skills()
    skill = skills.get(name)
    if not skill:
        return None
    
    return f"""<skill name="{skill.name}">
{skill.content}
</skill>"""
=======

def invalidate_entries_cache() -> None:
    """协议实现：重扫 agent + skill 索引（reload_all）。

    既有 routes 同时还会调用 invalidate_context_cache()（内部同样 reload_all），
    双调用仅多一次目录扫描，无副作用。
    """
    from harness.providers import reload_all

    reload_all()
>>>>>>> ce7fc48 (Agents/Skills的L1～L3重构完成（统一协议调度+文件驱动）)
