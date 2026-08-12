from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

from harness.core.capabilities.utils import EntityContent, render_l1_block
from harness.core.foundation.registry import BaseRegistry

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════


@dataclass
class AgentContent(EntityContent):
    # name / description / content / model 继承自 EntityContent
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)  # 声明式引用的 Skill
    max_tokens: int = 8192
    temperature: float = 0.5
    allow_autonomous: bool = False
    enable_critic: bool = False

    # 文件系统特有字段
    path: str = ""  # AGENT.md 所在目录
    private_skills_dir: str = ""  # 私有 Skill 目录路径


# ═══════════════════════════════════════════════════════════
# AGENT.md 解析器
# ═══════════════════════════════════════════════════════════


class AgentParser:
    """解析 Claude Code 格式的 AGENT.md 文件"""

    FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

    def parse_directory(self, agent_dir: Path) -> AgentContent | None:
        """解析一个 Agent 目录"""
        agent_md = agent_dir / "AGENT.md"
        if not agent_md.is_file():
            log.warning("目录缺少 AGENT.md", path=str(agent_dir))
            return None

        return self.parse_file(agent_md)

    def parse_file(self, agent_md: Path) -> AgentContent | None:
        """解析单个 AGENT.md 文件"""
        try:
            raw = agent_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log.error("读取 AGENT.md 失败", path=str(agent_md), error=str(e))
            return None

        # 分离 YAML front matter 和正文
        meta, body = self._split_front_matter(raw)

        # 必需字段缺省处理
        agent_dir = agent_md.parent
        name = meta.get("name", agent_dir.name)
        description = meta.get("description", "")

        # 检查私有 Skill 目录
        private_skills = str(agent_dir / "skills") if (agent_dir / "skills").is_dir() else ""

        return AgentContent(
            name=name,
            description=description,
            content=body.strip(),
            tools=meta.get("tools", []),
            skills=meta.get("skills", []),
            model=meta.get("model"),
            max_tokens=meta.get("max_tokens", 8192),
            temperature=meta.get("temperature", 0.5),
            allow_autonomous=meta.get("allow_autonomous", False),
            enable_critic=meta.get("enable_critic", False),
            path=str(agent_dir),
            private_skills_dir=private_skills,
        )

    def _split_front_matter(self, raw: str) -> tuple[dict, str]:
        """分离 YAML 头 和 Markdown 正文"""
        match = self.FRONT_MATTER_RE.match(raw)
        if not match:
            log.warning("AGENT.md 缺少 YAML front matter，整个文件作为正文")
            return {}, raw

        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as e:
            log.warning("YAML 解析失败", error=str(e))
            return {}, raw

        return meta, raw[match.end():]


# ═══════════════════════════════════════════════════════════
# Agent 注册表（文件系统驱动）
# ═══════════════════════════════════════════════════════════


class AgentRegistry(BaseRegistry):
    """运行时 Agent L1 摘要索引 + 完整定义缓存

    扫描 {VANTA_ROOT}/workspace/agents/*/AGENT.md
    """

    def __init__(self, agents_root: str | Path | None = None):
        super().__init__()

        if agents_root is None:
            vanta_root = os.getenv("VANTA_ROOT", str(Path.home() / "Vanta"))
            agents_root = Path(vanta_root) / "workspace" / "agents"

        self._agents_root = Path(agents_root)
        self._agents: dict[str, AgentContent] = {}  # 完整定义缓存
        self._parser = AgentParser()

    @property
    def agents_root(self) -> Path:
        return self._agents_root

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    # ── 加载 ─────────────────────────────────────────────

    def load(self) -> int:
        """扫描 agents_root 下所有 AGENT.md，构建内存索引"""
        if not self._agents_root.is_dir():
            log.warning("Agent 根目录不存在", path=str(self._agents_root))
            return 0

        loaded = 0
        for agent_dir in sorted(self._agents_root.iterdir()):
            if not agent_dir.is_dir():
                continue

            agent = self._parser.parse_directory(agent_dir)
            if agent is None:
                continue

            self._agents[agent.name] = agent
            self.register(agent.name, agent.description)
            loaded += 1

        log.info("Agent 加载完成", path=str(self._agents_root), count=loaded)
        return loaded

    def reload(self) -> int:
        """热更新"""
        self._agents.clear()
        self._index.clear()
        return self.load()

    # ── 查询 ─────────────────────────────────────────────

    def has(self, name: str) -> bool:
        return name in self._agents

    def get(self, name: str) -> AgentContent | None:
        return self._agents.get(name)

    def get_all(self) -> list[AgentContent]:
        return list(self._agents.values())

    def list_names(self) -> list[str]:
        return sorted(self._agents.keys())

    # ── Prompt 生成 ──────────────────────────────────────

    def as_prompt_block(self, name_filter: set[str] | None = None) -> str:
        """返回可注入 system prompt 的 L1 Agent 紧凑清单"""
        return render_l1_block(self._index, "# 可用 Agent 清单（Agent L1）", name_filter)

    def build_agent_prompt(self, name: str) -> str:
        """为指定 Agent 生成完整的 system prompt"""
        agent = self._agents.get(name)
        if not agent:
            return ""

        return f"""<agent name="{agent.name}">
{agent.content}
</agent>"""


# ═══════════════════════════════════════════════════════════
# 全局注册表单例管理
# ═══════════════════════════════════════════════════════════

_global_agent_registry: AgentRegistry | None = None


def get_agent_registry(agents_root: str | Path | None = None) -> AgentRegistry:
    """获取全局 AgentRegistry 单例"""
    global _global_agent_registry
    if _global_agent_registry is None:
        _global_agent_registry = AgentRegistry(agents_root)
        _global_agent_registry.load()
    return _global_agent_registry


def reset_agent_registry() -> None:
    """重置全局注册表（测试用）"""
    global _global_agent_registry
    _global_agent_registry = None


# ── 便捷函数 ─────────────────────────────────────────────

def load_agent(name: str, registry: AgentRegistry | None = None) -> AgentContent | None:
    """加载指定 Agent 的完整定义"""
    if registry is None:
        registry = get_agent_registry()
    return registry.get(name)