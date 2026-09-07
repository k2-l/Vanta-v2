"""集中配置。所有可调参数在此声明，运行时通过 get_settings() 获取。"""

import json
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class TomlConfigSource(PydanticBaseSettingsSource):
    """从 data/config.toml 读取配置，展平嵌套结构映射到 Settings 字段名。"""

    def __call__(self) -> dict[str, Any]:
        toml_path = Path("data/config.toml")
        if not toml_path.exists():
            return {}

        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return {}

        result: dict[str, Any] = {}

        # [anthropic] 节 — 映射到有 alias 的字段
        anthropic = data.get("anthropic", {})
        if "api_key" in anthropic:
            result["ANTHROPIC_API_KEY"] = anthropic["api_key"]
        if "auth_token" in anthropic:
            result["ANTHROPIC_AUTH_TOKEN"] = anthropic["auth_token"]
        if "base_url" in anthropic:
            result["ANTHROPIC_BASE_URL"] = anthropic["base_url"]

        # [server] 节
        server = data.get("server", {})
        if "host" in server:
            result["api_host"] = server["host"]
        if "port" in server:
            result["api_port"] = server["port"]
        if "log_level" in server:
            result["log_level"] = server["log_level"]
        if "cors_origins" in server:
            result["cors_origins"] = server["cors_origins"]

        # [auth] 节 — 有 alias 的用 alias，其余直接用字段名
        auth = data.get("auth", {})
        if "password" in auth:
            result["HARNESS_AUTH_PASSWORD"] = auth["password"]
        if "secret" in auth:
            result["HARNESS_AUTH_SECRET"] = auth["secret"]
        if "token_ttl_hours" in auth:
            result["auth_token_ttl_hours"] = auth["token_ttl_hours"]
        if "login_rate_limit" in auth:
            result["auth_login_rate_limit"] = auth["login_rate_limit"]

        # [mcp] 节 — 外部 MCP server 列表（TOML 的 [[mcp.servers]]）
        mcp = data.get("mcp", {})
        if "servers" in mcp:
            result["mcp_servers"] = mcp["servers"]

        # [permissions] 节 — 权限引擎（mode + allow/ask/deny 规则）
        permissions = data.get("permissions", {})
        if "mode" in permissions:
            result["permission_mode"] = permissions["mode"]
        if "allow" in permissions:
            result["permission_allow"] = permissions["allow"]
        if "ask" in permissions:
            result["permission_ask"] = permissions["ask"]
        if "deny" in permissions:
            result["permission_deny"] = permissions["deny"]
        if "reviewer" in permissions:
            result["approval_reviewer"] = permissions["reviewer"]

        # [embedding] / [rerank] 节 — 语义检索（Gitee AI 云端 embedding + rerank）
        embedding = data.get("embedding", {})
        if "model" in embedding:
            result["embedding_model"] = embedding["model"]
        if "base_url" in embedding:
            result["embedding_base_url"] = embedding["base_url"]
        if "api_key" in embedding:
            result["embedding_api_key"] = embedding["api_key"]
        rerank = data.get("rerank", {})
        if "enabled" in rerank:
            result["rerank_enabled"] = rerank["enabled"]
        if "model" in rerank:
            result["rerank_model"] = rerank["model"]
        if "recall_n" in rerank:
            result["rerank_recall_n"] = rerank["recall_n"]
        if "base_url" in rerank:
            result["rerank_base_url"] = rerank["base_url"]
        if "api_key" in rerank:
            result["rerank_api_key"] = rerank["api_key"]

        # [qdrant] 节 — 向量存储（Qdrant Cloud，云端唯一）
        qdrant = data.get("qdrant", {})
        if "url" in qdrant:
            result["qdrant_url"] = qdrant["url"]
        if "api_key" in qdrant:
            result["qdrant_api_key"] = qdrant["api_key"]

        # [github] 节 — GitHub REST API 访问令牌（fetcher.py 抓 GitHub 带认证）
        github = data.get("github", {})
        if "token" in github:
            result["github_token"] = github["token"]

        # [search] 节 — 联网搜索工具（WebSearch）后端
        search = data.get("search", {})
        if "provider" in search:
            result["search_provider"] = search["provider"]
        if "api_key" in search:
            result["search_api_key"] = search["api_key"]
        if "base_url" in search:
            result["search_base_url"] = search["base_url"]

        # [models] 节
        models = data.get("models", {})
        if "high" in models:
            result["model_high"] = models["high"]
        if "mid" in models:
            result["model_mid"] = models["mid"]
        if "low" in models:
            result["model_low"] = models["low"]

        # [database] 节
        database = data.get("database", {})
        if "url" in database:
            result["database_url"] = database["url"]

        # [paths] 节
        paths = data.get("paths", {})
        if "data_dir" in paths:
            result["data_dir"] = paths["data_dir"]
        if "profile_path" in paths:
            result["profile_path"] = paths["profile_path"]
        if "suite_dir" in paths:
            result["suite_dir"] = paths["suite_dir"]

        # [history] 节
        history = data.get("history", {})
        if "recent_n" in history:
            result["history_recent_n"] = history["recent_n"]
        if "token_budget" in history:
            result["history_token_budget"] = history["token_budget"]
        if "memory_top_k" in history:
            result["memory_top_k"] = history["memory_top_k"]

        # [limits] 节
        limits = data.get("limits", {})
        if "max_tokens_per_turn" in limits:
            result["max_tokens_per_turn"] = limits["max_tokens_per_turn"]
        if "max_tool_calls_per_turn" in limits:
            result["max_tool_calls_per_turn"] = limits["max_tool_calls_per_turn"]
        if "tool_timeout_seconds" in limits:
            result["tool_timeout_seconds"] = limits["tool_timeout_seconds"]
        if "max_tool_output_chars" in limits:
            result["max_tool_output_chars"] = limits["max_tool_output_chars"]
        if "tool_concurrency" in limits:
            result["tool_concurrency"] = limits["tool_concurrency"]
        if "agent_max_parallel" in limits:
            result["AGENT_MAX_PARALLEL"] = limits["agent_max_parallel"]
        if "session_token_limit" in limits:
            result["session_token_limit"] = limits["session_token_limit"]
        if "daily_token_limit" in limits:
            result["daily_token_limit"] = limits["daily_token_limit"]
        if "max_concurrent_sessions" in limits:
            result["max_concurrent_sessions"] = limits["max_concurrent_sessions"]

        # [context] 节
        context = data.get("context", {})
        if "compression_enabled" in context:
            result["context_compression_enabled"] = context["compression_enabled"]
        if "model_context_window" in context:
            result["model_context_window"] = context["model_context_window"]
        if "compression_ratio" in context:
            result["context_compression_ratio"] = context["compression_ratio"]
        if "summary_threshold" in context:
            result["context_summary_threshold"] = context["summary_threshold"]
        if "summary_target_chars" in context:
            result["context_summary_target_chars"] = context["summary_target_chars"]
        if "enable_prompt_cache" in context:
            result["enable_prompt_cache"] = context["enable_prompt_cache"]

        # [agent] 节
        agent = data.get("agent", {})
        if "graph_recursion_limit" in agent:
            result["graph_recursion_limit"] = agent["graph_recursion_limit"]
        if "summarize_keep_recent" in agent:
            result["summarize_keep_recent"] = agent["summarize_keep_recent"]
        if "summarize_max_tokens" in agent:
            result["summarize_max_tokens"] = agent["summarize_max_tokens"]
        if "max_tool_iterations" in agent:
            result["max_tool_iterations"] = agent["max_tool_iterations"]
        if "tool_failure_max_retries" in agent:
            result["tool_failure_max_retries"] = agent["tool_failure_max_retries"]
        if "max_recovery_attempts" in agent:
            result["max_recovery_attempts"] = agent["max_recovery_attempts"]
        if "slow_request_threshold_sec" in agent:
            result["slow_request_threshold_sec"] = agent["slow_request_threshold_sec"]
        if "enable_extended_thinking" in agent:
            result["enable_extended_thinking"] = agent["enable_extended_thinking"]
        if "thinking_budget_low" in agent:
            result["thinking_budget_low"] = agent["thinking_budget_low"]
        if "thinking_budget_mid" in agent:
            result["thinking_budget_mid"] = agent["thinking_budget_mid"]
        if "thinking_budget_high" in agent:
            result["thinking_budget_high"] = agent["thinking_budget_high"]

        # [sub_agent] 节
        sub_agent = data.get("sub_agent", {})
        if "max_tool_iterations" in sub_agent:
            result["sub_agent_max_tool_iterations"] = sub_agent["max_tool_iterations"]
        if "max_recovery_attempts" in sub_agent:
            result["sub_agent_max_recovery_attempts"] = sub_agent["max_recovery_attempts"]
        if "recursion_limit" in sub_agent:
            result["sub_agent_recursion_limit"] = sub_agent["recursion_limit"]
        if "max_depth" in sub_agent:
            result["sub_agent_max_depth"] = sub_agent["max_depth"]

        # 过滤掉空字符串（避免覆盖 Python 默认值）
        return {k: v for k, v in result.items() if v != ""}

    def get_field_value(self, field_name: str, field_info: Any) -> Any:  # type: ignore[override]
        return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HARNESS_",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, TomlConfigSource(settings_cls))

    # === 凭据：api_key（x-api-key 头）和 auth_token（Bearer）二选一 ===
    # 兼容场景：
    #   1. 官方 Anthropic：填 ANTHROPIC_API_KEY
    #   2. 第三方兼容服务（DeepSeek/Kimi/GLM/代理）：填 ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL
    #   3. Claude Code OAuth / Bearer 风格代理：填 ANTHROPIC_AUTH_TOKEN（可选 + BASE_URL）
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_auth_token: str | None = Field(default=None, alias="ANTHROPIC_AUTH_TOKEN")
    anthropic_base_url: str | None = Field(default=None, alias="ANTHROPIC_BASE_URL")

    api_host: str = "127.0.0.1"
    api_port: int = 8765

    # CORS：开发期 Vite dev server 默认 :5173；生产期可加自定义域名
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://localhost:5173",
        "https://127.0.0.1:5173",
    ]

    # 鉴权（云部署必填）
    auth_password: str = Field(default="", alias="HARNESS_AUTH_PASSWORD")
    auth_secret: str = Field(default="", alias="HARNESS_AUTH_SECRET")
    auth_token_ttl_hours: int = 168  # 默认 7 天
    auth_login_rate_limit: int = 5   # 每 IP 每分钟最多 5 次登录尝试

    # MCP（Model Context Protocol）外部工具服务器（见 harness/tools/mcp）
    # 每项 dict：{name, command, args?: list, env?: dict, enabled?: bool}
    mcp_servers: list[dict] = []

    # 插件工具来源（见 harness/tools/sources/plugin）：plugins_dir 下每个包暴露 get_tools()
    plugins_enabled: bool = False
    plugins_dir: str = "plugins"

    # 权限引擎（见 harness/infra/permissions）：mode + allow/ask/deny 规则（叠加在默认规则上）
    permission_mode: str = "default"   # default | acceptEdits | plan | bypass
    permission_allow: list[str] = []
    permission_ask: list[str] = []
    permission_deny: list[str] = []
    # ask 决策的审批方：human=阻塞式人工审批（前端决策）；audit_agent=LLM 自动裁决（model_low，
    # 默认放行常规操作、只拦破坏性动作，fail-closed）。见 harness/infra/audit_agent.py
    approval_reviewer: str = "human"   # human | audit_agent

    # 语义检索（harness/infra/vector）：Gitee AI 云端 embedding + ReRank 精排。
    # 云端唯一、无本地兜底：embedding_api_key 留空时 vector.py 直接 raise。
    embedding_model: str = "Qwen3-Embedding-8B"        # 实测输出 1024 维
    embedding_base_url: str = "https://ai.gitee.com/v1"
    embedding_api_key: str = ""
    rerank_enabled: bool = False
    rerank_model: str = "bge-reranker-v2-m3"
    rerank_recall_n: int = 20                          # 精排前的召回放大数
    # rerank 的 base_url/api_key 留空则复用 embedding 的（同一 Gitee 端点，免重复配置）；
    # 仅当 rerank 想走不同 provider 时才在 [rerank] 显式覆盖。
    rerank_base_url: str = ""
    rerank_api_key: str = ""

    # 向量存储（harness/infra/vector）：Qdrant Cloud。
    # 云端唯一、无本地兜底：qdrant_url 或 qdrant_api_key 留空时 vector.py 直接 raise。
    qdrant_url: str = ""
    qdrant_api_key: str = ""

    # GitHub REST API 访问令牌（harness/infra/fetcher 抓 GitHub 带认证）。
    # 留空则匿名访问（限流较低，public repo 足够用）；填写后提升限流额度。
    github_token: str = ""

    # WebSearch 检索后端：默认 duckduckgo（免费无 key）；配 provider=tavily + api_key 更稳。
    search_provider: str = "duckduckgo"  # duckduckgo | tavily
    search_api_key: str = ""
    search_base_url: str = ""  # 可选：自建/代理端点（如 tavily 兼容网关）

    # 三档模型：在 data/config.toml 中按需覆盖（[models] high / mid / low）
    model_high: str = "claude-opus-4-7"          # 高级：复杂推理、长上下文
    model_mid:  str = "claude-sonnet-4-6"         # 正常：主代理、子 agent 默认
    model_low:  str = "claude-haiku-4-5-20251001" # 低级：摘要、标题、旁路压缩

    # Extended thinking（仅官方 Anthropic 端点确认支持，第三方兼容代理可能不支持 thinking 参数）
    # 主开关默认关闭；某档 budget 设为 0 时即使总开关打开也不对该档启用
    enable_extended_thinking: bool = False
    thinking_budget_low: int = 2000    # summarize_node（model_low）
    thinking_budget_mid: int = 6000    # agent_node（model_mid）
    thinking_budget_high: int = 12000  # 预留：model_high 暂无调用方

    # 数据库（PostgreSQL）
    database_url: str = "postgresql+asyncpg://harness:harness_dev@localhost/harness"

    # 其他持久化路径
    data_dir: str = "data"
    profile_path: str = "data/profile.md"

    # 外部套件路径（security-suite 等）
    # workspace_dir: 工具执行时的 cwd，留空则用 Harness 根目录
    # skills_dir:    技能文件夹（包含 <name>/SKILL.md 子目录）
    # agents_dir:    Agent 文件夹（包含 <name>.md 文件）
    # 套件根目录（自动推断 workspace/skills/agents/references 子路径）
    suite_dir: str = ""

    @property
    def workspace_dir(self) -> str:
        return self.suite_dir

    @property
    def skills_dir(self) -> str:
        return f"{self.suite_dir}/skills" if self.suite_dir else ""

    @property
    def agents_dir(self) -> str:
        return f"{self.suite_dir}/agents" if self.suite_dir else ""

    @property
    def references_dir(self) -> str:
        return f"{self.suite_dir}/references" if self.suite_dir else ""

    # 历史装载策略
    history_recent_n: int = 16              # Supervisor 每次注入最近 N 条消息
    history_token_budget: int = 60_000     # 历史消息 token 上限（超出从头截断）
    memory_top_k: int = 5                   # 召回 top-K 长期记忆

    # Anthropic prompt caching（静态 system prompt 部分）
    # 默认关闭：部分非官方兼容端点不支持 cache_control，开启前请确认端点支持
    enable_prompt_cache: bool = False

    # 单次 LLM 响应最大 token 数
    max_tokens_per_turn: int = 4096

    # 单次 LLM 响应最多执行的工具数（0 = 不限，由 token 预算兜底；仍受 tool_concurrency 并发约束）
    max_tool_calls_per_turn: int = 0

    # 单工具执行超时（秒）
    tool_timeout_seconds: int = 60

    # 单工具输出字符上限（注入 LLM 前截断，防 context 溢出）
    max_tool_output_chars: int = 8_000

    # 子 agent context 参数超过此字符数时，用 model_low 做摘要压缩
    # 0 = 禁用摘要，退化为截断
    context_summary_threshold: int = 8_000   # 触发阈值，与 max_tool_output_chars 对齐
    context_summary_target_chars: int = 2_000  # 摘要后目标长度

    # 并发工具执行数（同一轮次内）
    tool_concurrency: int = 5

    # AgentCoordinator 最大并行任务数（环境变量 AGENT_MAX_PARALLEL）
    agent_max_parallel: int = Field(default=5, alias="AGENT_MAX_PARALLEL")

    # Token 预算（超限后拒绝继续推理）
    session_token_limit: int = 1_000_000    # tokens / 会话
    daily_token_limit: int = 10_000_000     # tokens / 天（全局）

    # 上下文压缩（Context Compression）—— 已改为「用户主动触发」，不再自动进流程。
    # context_compression_enabled 不再驱动任何自动路由（保留字段仅为配置兼容/前端读取）；
    # threshold 现用作前端「建议压缩」的软提示阈值（越过时提示用户，可手动压缩）。
    context_compression_enabled: bool = True   # 【已弃用于自动路由】保留兼容
    model_context_window: int = 200_000        # 模型上下文窗口大小（tokens）
    context_compression_ratio: float = 0.80   # 「建议压缩」软提示阈值比例（默认 80%）
    # 主动压缩：喂给压缩器的原文 token 上限；超出部分由已有摘要覆盖（从原文整体重生成）
    compaction_input_max_tokens: int = 120_000

    @property
    def context_compression_threshold(self) -> int:
        """「建议压缩」软提示的 token 阈值（= window × ratio）。前端据此提示用户可手动压缩。"""
        return int(self.model_context_window * self.context_compression_ratio)

    # 全局并发：同时运行的 session 上限（防止 DB/API 被打爆）
    max_concurrent_sessions: int = 20

    # LangGraph 图递归深度硬上限（安全网）。max_tool_iterations=0（不限）时即循环硬天花板，
    # token 预算为主兜底；>0 时须 > 3 + 2*(max_tool_iterations + max_recovery_attempts) + 余量。
    # _validate_graph_depth 启动时校验；溢出由 runtime 优雅收尾。
    graph_recursion_limit: int = 500

    # Rolling Summary：每次压缩保留最近 N 条消息
    summarize_keep_recent: int = 6
    # Rolling Summary 单次摘要调用的最大输出 token 数
    summarize_max_tokens: int = 1024

    # 工具循环检测：agent→tools→agent 最多迭代次数（0 = 不限，由 token 预算 + graph_recursion_limit 兜底）
    max_tool_iterations: int = 0

    # 单个工具累计失败上限（达到后在 ToolMessage 中提示 LLM 换用其他工具）
    tool_failure_max_retries: int = 3

    # 错误恢复最大重试次数（超出后 route_after_recovery → END）
    max_recovery_attempts: int = 3

    # 子 agent 参数（run_agent 工具调用的下级 agent）
    sub_agent_max_tool_iterations: int = 10   # 子 agent 工具循环上限（比主代理少）
    sub_agent_max_recovery_attempts: int = 2  # 子 agent 最大恢复次数
    sub_agent_recursion_limit: int = 30       # 子 agent 图递归深度上限
    sub_agent_max_depth: int = 2              # 调用链最大深度（0=主代理，1=子，2=孙）

    # 慢请求日志阈值（秒）；SSE/WS 路由自动豁免
    slow_request_threshold_sec: float = 30.0

    # 定价快照：USD per 1M tokens（input, output）。第三方服务可在 config.json 覆盖。
    # 格式：{model_id: [input_price, output_price]}（TOML/JSON 不支持 tuple，使用 list）
    price_per_m_tokens: dict[str, list[float]] = Field(
        default={
            "claude-opus-4-7":          [15.0, 75.0],
            "claude-sonnet-4-6":        [3.0, 15.0],
            "claude-haiku-4-5-20251001": [1.0, 5.0],
        }
    )

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_credentials(self) -> "Settings":
        if not (self.anthropic_api_key or self.anthropic_auth_token):
            raise ValueError(
                "必须设置 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN 之一。\n"
                "  - 官方 Anthropic：在 data/config.toml 的 [anthropic] 节填写 api_key\n"
                "  - 第三方兼容服务：填写 api_key + base_url\n"
                "  - Bearer/OAuth 代理：填写 auth_token\n"
                "  - 或通过环境变量 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 覆盖"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    # 叠加 data/config.json 中的运行时覆盖（前端配置写入）
    try:
        p = Path(s.data_dir) / "config.json"
        if p.exists():
            overrides = json.loads(p.read_text(encoding="utf-8"))
            if overrides:
                s = s.model_copy(update=overrides)
    except Exception:
        pass
    return s
