"""审计中可局部修复问题的安全回归测试。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import tempfile
import threading
import tomllib
import unittest
from contextlib import chdir
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

os.environ.setdefault("ANTHROPIC_API_KEY", "test-only-model-key")

from harness.app import auth as auth_module
from harness.app.schemas import ChatRequest
from harness.core.runtime import _failed_phase_events
from harness.infra import config_store, podman
from harness.infra.event_bus import EventBus
from harness.infra.settings import get_settings
from harness.routes import chat as chat_routes
from harness.routes import config as config_routes
from harness.routes import containers as container_routes
from harness.security import approvals
from harness.security.permissions import evaluate
from harness.tools.builtin.cmd.shell import ShellExecTool
from harness.tools.builtin.web._net import safe_public_url
from harness.tools.exec_context import (
    apply_active_engagement,
    apply_exec_env,
    get_exec_env,
)


class ApprovalAndExecutionTests(unittest.IsolatedAsyncioTestCase):
    def test_bash_approval_follows_command_risk(self) -> None:
        self.assertFalse(ShellExecTool.requires_approval)
        self.assertEqual(ShellExecTool.risk_level, "high")
        self.assertEqual(evaluate("Bash", {"command": "pwd"}), "allow")
        self.assertEqual(evaluate("Bash", {"command": "rg TODO harness"}), "allow")
        self.assertEqual(evaluate("Bash", {"command": "python script.py"}), "ask")
        self.assertEqual(evaluate("Bash", {"command": "new-unknown-command"}), "ask")
        self.assertEqual(evaluate("Bash", {"command": "rm -rf /"}), "deny")

    async def test_timeout_boundary_accepts_completed_approval(self) -> None:
        async def timeout_after_completion(_awaitable, **kwargs):
            del kwargs
            pending = next(iter(approvals._pending.values()))
            pending.set_result(True)
            await asyncio.sleep(0)
            raise TimeoutError

        with (
            patch("harness.security.approvals.event_bus.publish", new=AsyncMock()),
            patch("harness.security.approvals.asyncio.wait_for", side_effect=timeout_after_completion),
            patch("harness.security.approvals._record_expired_approval", new=AsyncMock()) as expired,
        ):
            allowed = await approvals.request_approval(
                "session-1", "Bash", "执行命令", timeout=0.01
            )

        self.assertTrue(allowed)
        expired.assert_not_awaited()


class EngagementPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ended_engagement_is_cleared_before_tool_execution(self) -> None:
        now = datetime.now(UTC)
        record = SimpleNamespace(
            id="eng-ended",
            name="ended",
            scope_targets=["example.com"],
            status="active",
            authorization_ref="approval-1",
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
            dns_resolver_ip="",
        )
        apply_exec_env("local")
        with (
            patch("harness.infra.db.get_active_engagement_id", new=AsyncMock(return_value=record.id)),
            patch("harness.infra.db.get_engagement", new=AsyncMock(return_value=record)),
            patch("harness.infra.db.set_active_engagement", new=AsyncMock()) as clear,
        ):
            await apply_active_engagement("session-1")

        self.assertFalse(get_exec_env().has_engagement)
        clear.assert_awaited_once_with("session-1", "")

    async def test_valid_engagement_is_applied_to_execution_context(self) -> None:
        now = datetime.now(UTC)
        record = SimpleNamespace(
            id="eng-active",
            name="active",
            scope_targets=["example.com"],
            status="active",
            authorization_ref="approval-1",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=1),
            dns_resolver_ip="1.1.1.1",
        )
        apply_exec_env("container:record-1")
        with (
            patch("harness.infra.db.get_active_engagement_id", new=AsyncMock(return_value=record.id)),
            patch("harness.infra.db.get_engagement", new=AsyncMock(return_value=record)),
            patch("harness.infra.db.set_active_engagement", new=AsyncMock()) as clear,
        ):
            await apply_active_engagement("session-1")

        env = get_exec_env()
        self.assertEqual(env.engagement_id, record.id)
        self.assertEqual(env.scope_targets, ("example.com",))
        self.assertEqual(env.container_id, "record-1")
        clear.assert_not_awaited()


class BoundaryProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_agent_lease_blocks_profile_mutation(self) -> None:
        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def scalar(self, _statement):
                return SimpleNamespace(container_record_id="record-1")

        with (
            patch.object(
                container_routes,
                "session_factory",
                return_value=lambda: FakeSession(),
            ),
            patch.object(
                container_routes,
                "get_or_404",
                new=AsyncMock(return_value=SimpleNamespace(container_id="podman-1")),
            ),
            patch.object(
                container_routes,
                "_active_lease_count",
                new=AsyncMock(return_value=1),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await container_routes.put_container_profile(
                    "record-1",
                    container_routes.ContainerProfileRequest(),
                    {},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("Agent invocation", raised.exception.detail)

    async def test_podman_name_collision_never_removes_existing_container(self) -> None:
        with patch(
            "harness.infra.podman._podman",
            new=AsyncMock(return_value=(125, "", "name is already in use")),
        ) as call:
            with self.assertRaises(RuntimeError):
                await podman.create_container("shared", "image", [], [])

        self.assertEqual(call.await_count, 1)
        self.assertEqual(call.await_args.args[0], "create")

    async def test_duplicate_container_record_is_rejected_before_podman(self) -> None:
        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def scalar(self, _statement):
                return "existing-id"

        with (
            patch.object(container_routes, "session_factory", return_value=lambda: FakeSession()),
            patch.object(container_routes.podman, "create_container", new=AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as raised:
                await container_routes.create_container(
                    container_routes.CreateContainerRequest(name="shared", image="image"), {}
                )

        self.assertEqual(raised.exception.status_code, 409)
        create.assert_not_awaited()

    async def test_unknown_chat_session_is_rejected_before_streaming(self) -> None:
        with patch.object(chat_routes.db, "get_session", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await chat_routes.chat(ChatRequest(message="hello", session_id="missing"), {})
        self.assertEqual(raised.exception.status_code, 404)


class NetworkAndQueueTests(unittest.IsolatedAsyncioTestCase):
    def test_hostname_resolving_to_loopback_is_rejected(self) -> None:
        answer = [(2, 1, 6, "", ("127.0.0.1", 80))]
        with patch("harness.tools.builtin.web._net.socket.getaddrinfo", return_value=answer):
            allowed, reason = safe_public_url("http://public.example/")
        self.assertFalse(allowed)
        self.assertIn("非公网", reason)

    async def test_article_redirect_is_rejected(self) -> None:
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        response = httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/admin"},
            request=httpx.Request("GET", "https://public.example"),
        )
        with (
            patch("harness.infra.fetcher.httpx.AsyncClient", return_value=FakeClient()) as client,
            patch("harness.infra.fetcher._http_get", new=AsyncMock(return_value=response)),
        ):
            from harness.infra.fetcher import _fetch_article

            with self.assertRaises(ValueError):
                await _fetch_article("https://public.example", ("93.184.216.34",))
        self.assertFalse(client.call_args.kwargs["follow_redirects"])

    async def test_pinned_transport_connects_to_validated_ip_with_original_sni(self) -> None:
        from harness.infra.fetcher import _PinnedTransport

        class InnerTransport:
            def __init__(self):
                self.request = None

            async def handle_async_request(self, request):
                self.request = request
                return httpx.Response(200, request=request)

            async def aclose(self):
                return None

        inner = InnerTransport()
        with patch("harness.infra.fetcher.httpx.AsyncHTTPTransport", return_value=inner):
            transport = _PinnedTransport("public.example", "93.184.216.34")
        request = httpx.Request("GET", "https://public.example/path")
        await transport.handle_async_request(request)

        self.assertEqual(inner.request.url.host, "93.184.216.34")
        self.assertEqual(inner.request.headers["host"], "public.example")
        self.assertEqual(inner.request.extensions["sni_hostname"], "public.example")

    async def test_slow_subscriber_queue_is_bounded_and_preserves_approval(self) -> None:
        bus = EventBus(max_queue_size=2)
        async with bus.subscribe("session-1") as queue:
            await bus.publish("session-1", {"seq": 1})
            await bus.publish("session-1", {"seq": 2})
            await bus.publish("session-1", {"seq": 3})
            await bus.publish("session-1", {"type": "approval_required", "seq": 4})
            self.assertEqual((await queue.get())["seq"], 2)
            self.assertEqual((await queue.get())["seq"], 4)


class PersistenceAndLifecycleTests(unittest.TestCase):
    def test_tracked_config_contains_no_credentials(self) -> None:
        config = tomllib.loads(Path("data/config.toml").read_text(encoding="utf-8"))
        secret_keys = {"api_key", "auth_token", "password", "secret", "token"}
        for section in config.values():
            if isinstance(section, dict):
                self.assertTrue(secret_keys.isdisjoint(section))
        self.assertTrue(
            {
                "anthropic_api_key",
                "anthropic_auth_token",
                "openai_api_key",
            }.isdisjoint(config_routes.EDITABLE)
        )

    def test_toml_credentials_are_rejected(self) -> None:
        environment = {
            "ANTHROPIC_API_KEY": "environment-model-key",
        }
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "config.toml").write_text(
                "\n".join(
                    (
                        '[anthropic]',
                        'api_key = "toml-model-key"',
                        '[auth]',
                        'password = "toml-password"',
                        'secret = "toml-secret-at-least-32-bytes"',
                        '[embedding]',
                        'api_key = "toml-embedding-key"',
                    )
                ),
                encoding="utf-8",
            )
            get_settings.cache_clear()
            try:
                with chdir(tmp), patch.dict(os.environ, environment, clear=False):
                    with self.assertRaisesRegex(ValueError, "禁止包含凭据字段"):
                        get_settings()
            finally:
                get_settings.cache_clear()

    def test_runtime_overrides_cannot_replace_environment_credentials(self) -> None:
        environment = {
            "ANTHROPIC_API_KEY": "environment-model-key",
            "HARNESS_AUTH_PASSWORD": "environment-password",
            "HARNESS_AUTH_SECRET": "environment-secret-at-least-32-bytes",
            "EMBEDDING_API_KEY": "environment-embedding-key",
        }
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "config.toml").write_text(
                '[paths]\ndata_dir = "data"\n',
                encoding="utf-8",
            )
            (data_dir / "config.local.json").write_text(
                json.dumps(
                    {
                        "anthropic_api_key": "runtime-model-key",
                        "auth_password": "runtime-password",
                        "auth_secret": "runtime-secret-at-least-32-bytes",
                        "embedding_api_key": "runtime-embedding-key",
                    }
                ),
                encoding="utf-8",
            )
            get_settings.cache_clear()
            try:
                with chdir(tmp), patch.dict(os.environ, environment, clear=False):
                    settings = get_settings()
            finally:
                get_settings.cache_clear()

        self.assertEqual(settings.anthropic_api_key, environment["ANTHROPIC_API_KEY"])
        self.assertEqual(settings.auth_password, environment["HARNESS_AUTH_PASSWORD"])
        self.assertEqual(settings.auth_secret, environment["HARNESS_AUTH_SECRET"])
        self.assertEqual(settings.embedding_api_key, environment["EMBEDDING_API_KEY"])

    def test_short_jwt_secret_is_rejected(self) -> None:
        settings = SimpleNamespace(auth_password="configured", auth_secret="too-short")
        with patch.object(auth_module, "get_settings", return_value=settings):
            with self.assertRaises(HTTPException) as raised:
                auth_module._ensure_configured()
        self.assertEqual(raised.exception.status_code, 503)

    def test_config_replace_failure_preserves_previous_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            config_store, "_invalidate_model_cache"
        ):
            config_store.save(tmp, {"model": "stable"})
            with patch.object(config_store.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    config_store.save(tmp, {"model": "partial"})

            self.assertEqual(config_store.load(tmp), {"model": "stable"})
            leftovers = list(Path(tmp).glob(".config.local.json.*.tmp"))
            self.assertEqual(leftovers, [])
            json.loads((Path(tmp) / "config.local.json").read_text(encoding="utf-8"))

    def test_concurrent_config_updates_do_not_lose_keys(self) -> None:
        workers = 8
        barrier = threading.Barrier(workers)

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            config_store, "_invalidate_model_cache"
        ):
            def update(index: int) -> None:
                barrier.wait()
                config_store.save(tmp, {f"key_{index}": index})

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(update, range(workers)))
            stored = config_store.load(tmp)

        self.assertEqual(stored, {f"key_{index}": index for index in range(workers)})

    def test_malformed_runtime_config_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.local.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                config_store.save(tmp, {"model": "new"})
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_settings_fail_closed_on_malformed_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "config.toml").write_text(
                '[anthropic]\napi_key = "test-key"\n[paths]\ndata_dir = "data"\n',
                encoding="utf-8",
            )
            (data_dir / "config.local.json").write_text("{broken", encoding="utf-8")
            environment = {"ANTHROPIC_API_KEY": "test-key"}
            get_settings.cache_clear()
            try:
                with chdir(tmp), patch.dict(os.environ, environment, clear=False):
                    with self.assertRaises(ValueError):
                        get_settings()
            finally:
                get_settings.cache_clear()

    def test_failed_run_closes_root_and_pending_phases(self) -> None:
        events = _failed_phase_events("reviewer", {"skill:audit", "agent:reviewer"})
        self.assertEqual({event.id for event in events}, {"agent", "agent:reviewer", "skill:audit"})
        self.assertTrue(all(event.status == "failed" for event in events))


if __name__ == "__main__":
    unittest.main()
