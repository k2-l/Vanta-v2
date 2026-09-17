"""Automatic Agent runtime selection and invocation binding regressions."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harness.contracts.models import AgentFull, EntityMeta
from harness.core.runtime_resolver import (
    RuntimeCandidate,
    RuntimeRequirements,
    RuntimeResolutionError,
    rank_candidates,
)
from harness.infra import podman
from harness.security.permissions import evaluate
from harness.tools.builtin.orchestration.run_agent import RunAgentTool


def _candidate(
    name: str,
    *,
    capabilities: tuple[str, ...],
    network: str = "none",
    workspace: str = "none",
    allowlist: tuple[str, ...] = ("audit-agent",),
) -> RuntimeCandidate:
    return RuntimeCandidate(
        record_id=f"record-{name}",
        podman_id=f"podman-{name}",
        name=name,
        capabilities=capabilities,
        network_policy=network,
        workspace_mode=workspace,
        default_workdir="",
        max_concurrency=1,
        agent_ready=True,
        agent_allowlist=allowlist,
    )


class RuntimeSelectionTests(unittest.TestCase):
    def test_plain_agent_container_does_not_bypass_engagement_for_scanners(self) -> None:
        self.assertEqual(
            evaluate("Bash", {"command": "nmap 10.0.0.1"}, env="container", engaged=False),
            "deny",
        )

    def test_rank_requires_allowlist_and_capability_superset(self) -> None:
        requirements = RuntimeRequirements.from_input(
            {"capabilities": ["JDK17", "semgrep"], "network": "none"}
        )
        exact = _candidate("exact", capabilities=("jdk17", "semgrep"))
        oversized = _candidate(
            "oversized", capabilities=("jdk17", "semgrep", "docker"), network="internet"
        )
        missing = _candidate("missing", capabilities=("jdk17",))
        forbidden = _candidate(
            "forbidden", capabilities=("jdk17", "semgrep"), allowlist=("other-agent",)
        )

        ranked = rank_candidates(
            [oversized, missing, forbidden, exact],
            agent_name="audit-agent",
            requirements=requirements,
        )

        self.assertEqual([candidate.name for candidate in ranked], ["exact"])

    def test_rank_prefers_least_privilege_when_policy_is_unspecified(self) -> None:
        requirements = RuntimeRequirements.from_input({"capabilities": ["python3"]})
        isolated = _candidate("isolated", capabilities=("python3",), network="none")
        online = _candidate("online", capabilities=("python3",), network="internet")

        ranked = rank_candidates(
            [online, isolated], agent_name="audit-agent", requirements=requirements
        )

        self.assertEqual([candidate.name for candidate in ranked], ["isolated", "online"])

    def test_invalid_requirement_is_rejected_before_runtime_lookup(self) -> None:
        with self.assertRaises(RuntimeResolutionError) as caught:
            RuntimeRequirements.from_input({"network": "host"})
        self.assertEqual(caught.exception.code, "INVALID_RUNTIME_REQUIREMENTS")


class RuntimeReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_network_profile_requires_live_none_network(self) -> None:
        with (
            patch.object(podman, "is_running", new=AsyncMock(return_value=True)),
            patch.object(podman, "network_mode", new=AsyncMock(return_value="bridge")),
            patch.object(podman, "exec", new=AsyncMock()) as execute,
        ):
            result = await podman.probe_agent_runtime(
                "podman-1", expected_network_policy="none"
            )

        self.assertFalse(result.ready)
        self.assertIn("实际网络模式", result.reason)
        execute.assert_not_awaited()

    async def test_runtime_contract_probe_checks_common_commands(self) -> None:
        with (
            patch.object(podman, "is_running", new=AsyncMock(return_value=True)),
            patch.object(podman, "network_mode", new=AsyncMock(return_value="none")),
            patch.object(
                podman,
                "exec",
                new=AsyncMock(return_value=podman.ExecResult(0, "", "")),
            ) as execute,
        ):
            result = await podman.probe_agent_runtime(
                "podman-1",
                working_dir="/workspace",
                require_write=True,
                expected_network_policy="none",
            )

        self.assertTrue(result.ready)
        command = execute.await_args.args[1]
        self.assertEqual(command[:2], ["sh", "-c"])
        self.assertIn("command -v tee", command[2])
        self.assertIn("test -w /workspace", command[2])


class RunAgentRuntimeBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_requirement_binds_only_the_child_invocation(self) -> None:
        agent = AgentFull(meta=EntityMeta("audit-agent", "test"), content="do work")
        provider = SimpleNamespace(get=lambda _name: agent)
        settings = SimpleNamespace(
            sub_agent_max_depth=3,
            max_agent_delegations_per_agent=3,
            max_agent_invocations_per_turn=10,
        )
        resolved = SimpleNamespace(
            execution_env="container:record-java",
            lease_id="lease-1",
        )

        with (
            patch("harness.infra.settings.get_settings", return_value=settings),
            patch("harness.providers.get_provider", return_value=provider),
            patch(
                "harness.tools.builtin.orchestration.run_agent.reserve_delegation",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "harness.tools.builtin.orchestration.run_agent.release_delegation",
                new=AsyncMock(),
            ),
            patch(
                "harness.tools.builtin.orchestration.run_agent.get_orchestration_context",
                return_value=None,
            ),
            patch(
                "harness.core.runtime_resolver.resolve_runtime",
                new=AsyncMock(return_value=resolved),
            ) as resolve,
            patch(
                "harness.core.runtime_resolver.release_runtime", new=AsyncMock()
            ) as release,
            patch(
                "harness.tools.builtin.orchestration.run_agent.run_sub_agent",
                new=AsyncMock(return_value="done"),
            ) as run_sub,
        ):
            result = await RunAgentTool().run(
                name="audit-agent",
                task="audit java",
                runtime_requirements={"capabilities": ["jdk17"]},
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.output, "done")
        self.assertEqual(resolve.await_args.kwargs["requirements"].capabilities, ("jdk17",))
        self.assertEqual(run_sub.await_args.kwargs["execution_env"], "container:record-java")
        release.assert_awaited_once_with("lease-1")

    async def test_omitted_requirement_preserves_inheritance(self) -> None:
        agent = AgentFull(meta=EntityMeta("audit-agent", "test"), content="do work")
        provider = SimpleNamespace(get=lambda _name: agent)
        settings = SimpleNamespace(
            sub_agent_max_depth=3,
            max_agent_delegations_per_agent=3,
            max_agent_invocations_per_turn=10,
        )

        with (
            patch("harness.infra.settings.get_settings", return_value=settings),
            patch("harness.providers.get_provider", return_value=provider),
            patch(
                "harness.tools.builtin.orchestration.run_agent.reserve_delegation",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "harness.tools.builtin.orchestration.run_agent.release_delegation",
                new=AsyncMock(),
            ),
            patch(
                "harness.tools.builtin.orchestration.run_agent.get_orchestration_context",
                return_value=None,
            ),
            patch(
                "harness.core.runtime_resolver.resolve_runtime", new=AsyncMock()
            ) as resolve,
            patch(
                "harness.tools.builtin.orchestration.run_agent.run_sub_agent",
                new=AsyncMock(return_value="done"),
            ) as run_sub,
        ):
            result = await RunAgentTool().run(name="audit-agent", task="audit")

        self.assertTrue(result.ok)
        resolve.assert_not_awaited()
        self.assertIsNone(run_sub.await_args.kwargs["execution_env"])


if __name__ == "__main__":
    unittest.main()
