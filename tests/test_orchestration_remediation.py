from __future__ import annotations

import tempfile
import unittest
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

environ.setdefault("ANTHROPIC_API_KEY", "test-only-model-key")

from harness.agents.provider import AgentProvider
from harness.contracts.models import AgentFull, EntityMeta
from harness.core.capabilities.services import _ask_title
from harness.core.context.usage import SessionUsage, Usage
from harness.core.foundation.internal_sections import (
    InternalSectionStreamFilter,
    strip_internal_sections,
)
from harness.core.foundation.tokens import estimate_tokens
from harness.core.graph.nodes.recovery import recovery_node
from harness.core.graph.routes import route_after_agent
from harness.core.graph.subagent.build import build_sub_graph
from harness.core.graph.subagent.context import (
    current_agent_lineage,
    current_invocation_id,
    enter_agent_invocation,
    get_orchestration_context,
    release_delegation,
    reserve_delegation,
    reset_orchestration_context,
    start_orchestration_context,
)
from harness.core.graph.subagent.nodes import _parse_critic_json, critic_node
from harness.core.graph.tool_exec import _persist_and_truncate
from harness.infra.settings import Settings
from harness.routes.agents import (
    AgentPatch,
    RegisterAgentRequest,
    get_agent,
    register_agent,
    update_agent,
)
from harness.tools.builtin.orchestration.run_agent import RunAgentTool
from harness.tools.registry import ToolRegistry


class InternalSectionTests(unittest.TestCase):
    def test_complete_and_unclosed_sections_are_private(self) -> None:
        self.assertEqual(
            strip_internal_sections(
                "公开<scratchpad>秘密</scratchpad>结论<subgoal>内部目标</subgoal>完成"
            ),
            "公开结论完成",
        )
        self.assertEqual(strip_internal_sections("公开<scratchpad>秘密"), "公开")
        self.assertEqual(strip_internal_sections("公开<SCRATCHPAD mode='x'>秘密"), "公开")

    def test_stream_filter_handles_split_tags(self) -> None:
        stream_filter = InternalSectionStreamFilter()
        chunks = [
            "公开<scr",
            "atchpad>秘密",
            "</scratchpad>结论<sub",
            "goal>目标</subgoal>完成",
        ]
        self.assertEqual("".join(stream_filter.feed(chunk) for chunk in chunks), "公开结论完成")


class ToolRegistryContractTests(unittest.TestCase):
    def test_removed_legacy_tool_names_do_not_resolve(self) -> None:
        registry = ToolRegistry()
        registry.register(SimpleNamespace(name="Agent"))
        self.assertIn("Agent", registry)
        for legacy_name in ("run_agent", "load_skill", "Sudo_Bash"):
            self.assertNotIn(legacy_name, registry)
            with self.assertRaises(KeyError):
                registry.get(legacy_name)


class DelegationGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_title_uses_explicit_tier_provider(self) -> None:
        response = AIMessage(content="测试标题")
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
        with patch(
            "harness.core.capabilities.services.build_chat_model",
            return_value=model,
        ) as build:
            title = await _ask_title("用户问题", "助手回答", "deepseek-chat", "openai")
        self.assertEqual(title, "测试标题")
        build.assert_called_once_with(
            provider="openai",
            model="deepseek-chat",
            max_tokens=512,
        )

    async def test_agent_api_round_trips_and_clears_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(environ, {"VANTA_ROOT": tmp}):
            created = await register_agent(
                RegisterAgentRequest(
                    md=(
                        "---\nname: worker\ndescription: d\n"
                        "model: deepseek-chat\nprovider: OpenAI\n---\nbody"
                    )
                ),
                {},
            )
            self.assertEqual(created["provider"], "openai")

            updated = await update_agent("worker", AgentPatch(provider=None), {})
            self.assertIsNone(updated["provider"])
            loaded = await get_agent("worker", {})
            self.assertIsNone(loaded["provider"])

    async def test_fenced_json_and_low_scores_reach_critic_retry(self) -> None:
        response = AIMessage(
            content=(
                "```json\n"
                '{"completeness": 2, "accuracy": 4, "actionability": 2, "verdict": "PASS"}'
                "\n```"
            ),
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 10}},
        )
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
        settings = SimpleNamespace(
            sub_agent_token_limit=1000,
            model_low="critic-model",
            model_low_provider=None,
            anthropic_api_key="key",
            anthropic_base_url="",
            summarize_max_tokens=100,
        )
        state = {
            "messages": [HumanMessage(content="task"), AIMessage(content="answer")],
            "session_id": "s",
            "agent_name": "worker",
            "invocation_tokens": 0,
            "token_limit": 1000,
            "critic_attempts": 0,
        }
        with (
            patch(
                "harness.core.graph.subagent.nodes.get_settings",
                return_value=settings,
            ),
            patch(
                "harness.core.graph.subagent.nodes._get_base_model",
                return_value=model,
            ),
            patch(
                "harness.core.graph.subagent.nodes.check_budget",
                new=AsyncMock(return_value=(0, 0)),
            ),
            patch(
                "harness.core.graph.subagent.nodes.record_usage",
                new=AsyncMock(),
            ),
        ):
            update = await critic_node(state, {})
        self.assertEqual(update["critic_attempts"], 1)
        self.assertNotIn("critic_passed", update)

    async def test_direct_limit_counts_active_children_and_releases(self) -> None:
        token = start_orchestration_context(max_invocations=39, max_parallel=5)
        try:
            self.assertIsNone(await reserve_delegation("agent", 3))
            self.assertIsNone(await reserve_delegation("agent", 3))
            self.assertIsNone(await reserve_delegation("agent", 3))
            self.assertEqual(await reserve_delegation("agent", 3), "DELEGATION_LIMIT")
            await release_delegation("agent")
            self.assertIsNone(await reserve_delegation("agent", 3))
            self.assertIsNone(await reserve_delegation("agent/child", 3))
            orchestration = get_orchestration_context()
            self.assertIsNotNone(orchestration)
            self.assertEqual(orchestration.total_invocations, 5)
        finally:
            reset_orchestration_context(token)

    async def test_six_serial_delegations_fit_three_active_slots(self) -> None:
        token = start_orchestration_context(max_invocations=39, max_parallel=5)
        try:
            for _ in range(6):
                self.assertIsNone(await reserve_delegation("agent", 3))
                await release_delegation("agent")
            orchestration = get_orchestration_context()
            self.assertIsNotNone(orchestration)
            self.assertEqual(orchestration.total_invocations, 6)
            self.assertNotIn("agent", orchestration.active_direct_by_parent)
        finally:
            reset_orchestration_context(token)

    async def test_releasing_slot_does_not_refund_total_guard(self) -> None:
        token = start_orchestration_context(max_invocations=3, max_parallel=3)
        try:
            for _ in range(3):
                self.assertIsNone(await reserve_delegation("agent", 3))
                await release_delegation("agent")
            self.assertEqual(
                await reserve_delegation("agent", 3),
                "AGENT_INVOCATION_LIMIT",
            )
        finally:
            reset_orchestration_context(token)

    async def test_run_agent_allows_six_completed_serial_calls(self) -> None:
        settings = SimpleNamespace(
            sub_agent_max_depth=3,
            max_agent_delegations_per_agent=3,
            max_agent_invocations_per_turn=39,
        )
        agent = AgentFull(EntityMeta("worker", "test"), "body")
        provider = SimpleNamespace(get=lambda _name: agent)
        token = start_orchestration_context(max_invocations=39, max_parallel=5)
        try:
            with (
                patch("harness.infra.settings.get_settings", return_value=settings),
                patch("harness.providers.get_provider", return_value=provider),
                patch(
                    "harness.tools.builtin.orchestration.run_agent.run_sub_agent",
                    new=AsyncMock(return_value="done"),
                ),
            ):
                for _ in range(6):
                    result = await RunAgentTool().run("worker", "task")
                    self.assertTrue(result.ok)
            orchestration = get_orchestration_context()
            self.assertIsNotNone(orchestration)
            self.assertEqual(orchestration.total_invocations, 6)
            self.assertNotIn("agent", orchestration.active_direct_by_parent)
        finally:
            reset_orchestration_context(token)

    async def test_invocation_identity_and_lineage_are_scoped(self) -> None:
        self.assertEqual(current_invocation_id(), "agent")
        with enter_agent_invocation("agent/call-1", "reviewer"):
            self.assertEqual(current_invocation_id(), "agent/call-1")
            self.assertEqual(current_agent_lineage(), ("reviewer",))
        self.assertEqual(current_invocation_id(), "agent")
        self.assertEqual(current_agent_lineage(), ())

    async def test_exhausted_invocation_pairs_tools_and_forces_final_answer(self) -> None:
        pending = AIMessage(
            content="",
            tool_calls=[{"name": "Read", "args": {"path": "x"}, "id": "call-1"}],
        )
        state = {
            "messages": [pending],
            "invocation_tokens": 10,
            "token_limit": 10,
            "tool_iterations": 1,
            "max_tool_iterations": 20,
            "error": None,
            "error_type": None,
        }
        self.assertEqual(route_after_agent(state), "recovery")
        update = await recovery_node(state, {})
        self.assertTrue(update["force_finalize"])
        self.assertIsInstance(update["messages"][0], ToolMessage)
        self.assertEqual(update["messages"][0].tool_call_id, "call-1")


class ConfigurationAndAccountingTests(unittest.TestCase):
    def test_critic_json_accepts_markdown_fence_and_leading_text(self) -> None:
        fenced = (
            "下面是评估结果：\n```json\n"
            '{"completeness": 4, "accuracy": 5, "actionability": 3, "verdict": "PASS"}'
            "\n```"
        )
        result = _parse_critic_json(fenced)
        self.assertEqual(result["verdict"], "PASS")

    def test_agent_provider_parses_critic_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = Path(tmp, "reviewer")
            agent_dir.mkdir()
            Path(agent_dir, "AGENT.md").write_text(
                "---\nname: reviewer\ndescription: test\nenable_critic: false\n---\nbody",
                encoding="utf-8",
            )
            agent = AgentProvider(tmp).get("reviewer")
            self.assertIsNotNone(agent)
            self.assertFalse(agent.enable_critic)

    def test_critic_node_is_registered_only_when_enabled(self) -> None:
        meta = EntityMeta(name="reviewer", description="test")
        enabled = build_sub_graph(AgentFull(meta, "body", enable_critic=True), 1)
        disabled = build_sub_graph(AgentFull(meta, "body", enable_critic=False), 1)
        self.assertIn("critic", enabled.get_graph().nodes)
        self.assertNotIn("critic", disabled.get_graph().nodes)

    def test_zero_budgets_and_loop_limits_are_rejected(self) -> None:
        for field in (
            "session_token_limit",
            "daily_token_limit",
            "main_agent_token_limit",
            "sub_agent_token_limit",
            "max_tool_iterations",
            "max_tool_calls_per_turn",
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Settings(**{field: 0})

    def test_default_delegation_tree_matches_three_by_three(self) -> None:
        settings = Settings()
        self.assertEqual(settings.max_agent_delegations_per_agent, 3)
        self.assertEqual(settings.sub_agent_max_depth, 3)
        self.assertGreaterEqual(settings.max_agent_invocations_per_turn, 3 + 9 + 27)
        with self.assertRaises(ValidationError):
            Settings(max_agent_invocations_per_turn=38)

    def test_mixed_model_cost_is_summed_per_model(self) -> None:
        usage = SessionUsage(
            session_id="s",
            by_model={
                "cheap": Usage(1_000_000, 0, "cheap"),
                "expensive": Usage(0, 1_000_000, "expensive"),
            },
        )
        with patch(
            "harness.core.context.usage._get_price_table",
            return_value={"cheap": (1.0, 2.0), "expensive": (10.0, 20.0)},
        ):
            self.assertEqual(usage.cost_usd(), 21.0)

    def test_cjk_estimate_is_not_len_divided_by_four(self) -> None:
        text = "这是一个中文令牌估算测试"
        self.assertGreater(estimate_tokens(text), len(text) // 4)


class ToolOutputPersistenceTests(unittest.TestCase):
    def test_large_output_file_has_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "harness.core.graph.tool_exec.get_settings",
                return_value=SimpleNamespace(workspace_dir=tmp),
            ):
                pointer = _persist_and_truncate("x" * 100, "Read", 10)
            rel = pointer.rsplit("：", 1)[-1].rstrip("]")
            output = Path(tmp, rel)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)


class TestProviderRouting(unittest.TestCase):
    """多 API 兼容 + 统一协议路由（Anthropic / OpenAI）。"""

    def test_infer_provider_by_prefix(self):
        from harness.core.graph import providers as p

        self.assertEqual(p.infer_provider("claude-opus-4-8"), p.ANTHROPIC)
        self.assertEqual(p.infer_provider("gpt-5.5"), p.OPENAI)
        self.assertEqual(p.infer_provider("o3-mini"), p.OPENAI)

    def test_infer_provider_fallback_to_default(self):
        from harness.core.graph import providers as p

        # 无法按名推断（第三方兼容端点命名）→ 回退 default_provider
        with patch.object(
            p, "get_settings", return_value=SimpleNamespace(default_provider="openai")
        ):
            self.assertEqual(p.infer_provider("deepseek-v4-flash"), p.OPENAI)

    def test_resolve_explicit_overrides_inference(self):
        from harness.core.graph import providers as p

        # 手工选择：显式 provider 覆盖模型名推断（子代理跨 provider 的关键）
        self.assertEqual(p.resolve_provider("openai", "claude-opus-4-8"), p.OPENAI)
        self.assertEqual(p.resolve_provider("anthropic", "gpt-5.5"), p.ANTHROPIC)
        # 非法显式值必须 fail-fast，不能静默改投另一 provider
        with self.assertRaises(ValueError):
            p.resolve_provider("bogus", "gpt-5.5")

    def test_build_chat_model_rejects_unknown_provider(self):
        from harness.core.graph import providers as p

        with self.assertRaises(ValueError):
            p.build_chat_model(provider="bogus", model="custom-model", max_tokens=64)

    def test_capability_gates_are_anthropic_only(self):
        from harness.core.graph import providers as p

        self.assertTrue(p.supports_prompt_cache(p.ANTHROPIC))
        self.assertFalse(p.supports_prompt_cache(p.OPENAI))
        self.assertTrue(p.supports_thinking(p.ANTHROPIC))
        self.assertFalse(p.supports_thinking(p.OPENAI))

    def test_build_chat_model_dispatches_by_provider(self):
        from harness.core.graph import providers as p

        stub = SimpleNamespace(
            openai_api_key="k", openai_base_url="",
            anthropic_api_key="k", anthropic_auth_token=None, anthropic_base_url="",
        )
        with patch.object(p, "get_settings", return_value=stub):
            from langchain_anthropic import ChatAnthropic
            from langchain_openai import ChatOpenAI

            m_oai = p.build_chat_model(provider=p.OPENAI, model="gpt-5.5", max_tokens=64)
            m_ant = p.build_chat_model(provider=p.ANTHROPIC, model="claude-x", max_tokens=64)
            self.assertIsInstance(m_oai, ChatOpenAI)
            self.assertIsInstance(m_ant, ChatAnthropic)

    def test_anthropic_auth_token_uses_bearer_header(self):
        from harness.core.graph import providers as p

        stub = SimpleNamespace(
            anthropic_api_key=None, anthropic_auth_token="oauth-xyz", anthropic_base_url="",
            openai_api_key=None, openai_base_url="",
        )
        with (
            patch.object(p, "get_settings", return_value=stub),
            patch.dict(environ, {"ANTHROPIC_API_KEY": ""}),
        ):
            m = p.build_chat_model(provider=p.ANTHROPIC, model="claude-x", max_tokens=32)
        # Bearer/OAuth token 走 Authorization 头，且不发 x-api-key（api_key 不设置）
        self.assertEqual(
            (getattr(m, "default_headers", None) or {}).get("Authorization"), "Bearer oauth-xyz"
        )
        self.assertFalse(bool(getattr(m, "anthropic_api_key", None)))

    def test_extract_usage_normalizes_across_providers(self):
        from harness.core.graph.providers import extract_usage

        # LangChain 归一化 usage_metadata（两 provider 通用）
        norm = AIMessage(
            content="x",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 3,
                "total_tokens": 13,
                "input_token_details": {"cache_read": 4, "cache_creation": 1},
            },
        )
        self.assertEqual(extract_usage(norm), (10, 3, 4, 1))
        # 回退：原始 Anthropic 风格 response_metadata.usage
        legacy = AIMessage(content="x")
        legacy.response_metadata = {"usage": {"input_tokens": 7, "output_tokens": 2}}
        self.assertEqual(extract_usage(legacy), (7, 2, 0, 0))


class TestCredentialValidation(unittest.TestCase):
    """多 provider 凭据校验：至少一个 provider 凭据即可（含纯 OpenAI）。"""

    def test_openai_only_config_validates(self):
        from harness.infra.settings import Settings

        s = Settings(OPENAI_API_KEY="sk-oai", ANTHROPIC_API_KEY=None, ANTHROPIC_AUTH_TOKEN=None)
        self.assertEqual(s.openai_api_key, "sk-oai")

    def test_anthropic_auth_token_only_validates(self):
        from harness.infra.settings import Settings

        # auth_token-only 现在是合法配置（且运行时会走 Bearer，不再是配置陷阱）
        Settings(ANTHROPIC_AUTH_TOKEN="oauth", ANTHROPIC_API_KEY=None)

    def test_no_credentials_rejected(self):
        from harness.infra.settings import Settings

        with self.assertRaises(ValidationError):
            Settings(ANTHROPIC_API_KEY=None, ANTHROPIC_AUTH_TOKEN=None, OPENAI_API_KEY=None)

    def test_provider_names_are_normalized_and_validated(self):
        normalized = Settings(OPENAI_API_KEY="x", default_provider=" OpenAI ")
        self.assertEqual(normalized.default_provider, "openai")
        with self.assertRaises(ValidationError):
            Settings(OPENAI_API_KEY="x", model_mid_provider="openaai")


class TestAgentProviderFrontmatter(unittest.TestCase):
    """agent frontmatter 的 provider 字段解析（手工跨 provider 选择入口）。"""

    def test_provider_field_parsed_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "worker"
            d.mkdir()
            (d / "AGENT.md").write_text(
                "---\nname: worker\ndescription: d\nmodel: gpt-5.5\nprovider: openai\n---\nbody",
                encoding="utf-8",
            )
            agent = AgentProvider(root).get("worker")
            self.assertEqual(agent.model, "gpt-5.5")
            self.assertEqual(agent.provider, "openai")

    def test_invalid_frontmatter_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "worker"
            d.mkdir()
            (d / "AGENT.md").write_text(
                "---\nname: worker\ndescription: d\nprovider: openaai\n---\nbody",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不支持的 provider"):
                AgentProvider(root).get("worker")


if __name__ == "__main__":
    unittest.main()
