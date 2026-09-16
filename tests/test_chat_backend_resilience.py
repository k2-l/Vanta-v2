"""客户端基础对话所依赖的后端降级与工作区回归。"""

import asyncio
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

os.environ.setdefault("ANTHROPIC_API_KEY", "test-only-model-key")

from harness.app.main import create_app, ensure_workspace
from harness.app.schemas import HealthResponse
from harness.core.capabilities.memory import automatic_memory_available, recall_as_context
from harness.core.runtime import _persist_answer, _remember_best_effort
from harness.infra.settings import get_settings
from harness.providers import get_provider
from harness.routes._utils import artifact_to_dict
from harness.routes.chat import (
    ApprovalDecision,
    _record_runtime_event,
    _retry_approval_audits,
    submit_approval_decision,
)
from harness.security.approvals import list_pending, request_approval
from harness.tools.builtin.cmd.file_ops import _sandbox_path
from harness.tools.builtin.cmd.shell import _exec_command, _resolve_cwd
from harness.tools.builtin.security.board import _media_type


class OptionalMemoryAvailabilityTests(unittest.TestCase):
    def test_unconfigured_qdrant_is_skipped_without_vector_request(self) -> None:
        settings = SimpleNamespace(qdrant_url="", qdrant_api_key="", embedding_api_key="key")
        self.assertFalse(automatic_memory_available(settings))
        with patch("harness.core.capabilities.memory.get_settings", return_value=settings), patch(
            "harness.core.capabilities.memory.vector.search_memory"
        ) as search:
            self.assertEqual(recall_as_context("你好"), "")
            search.assert_not_called()


class DesktopBackendContractTests(unittest.TestCase):
    def test_health_declares_the_desktop_contract(self) -> None:
        health = HealthResponse(status="ok", version="test")
        self.assertEqual(health.api_version, "1")
        self.assertTrue(health.capabilities.run_snapshot)
        self.assertTrue(health.capabilities.run_history)
        self.assertTrue(health.capabilities.artifact_export)

    def test_every_desktop_operation_has_a_backend_route(self) -> None:
        paths = create_app().openapi()["paths"]
        required = {
            "/health": "get",
            "/auth/login": "post",
            "/auth/me": "get",
            "/chat": "post",
            "/chat/approvals": "get",
            "/chat/approvals/history": "get",
            "/chat/approvals/{call_id}": "post",
            "/sessions": "get",
            "/runs": "get",
            "/sessions/{session_id}/messages": "get",
            "/sessions/{session_id}/phases": "get",
            "/sessions/{session_id}/events": "get",
            "/budget/{session_id}": "get",
            "/v1/artifacts": "get",
            "/v1/artifacts/{artifact_id}": "get",
            "/v1/agents": "get",
            "/v1/skills": "get",
            "/v1/mcp/servers": "get",
            "/v1/knowledge": "get",
            "/v1/containers": "get",
        }
        for path, method in required.items():
            self.assertIn(path, paths)
            self.assertIn(method, paths[path])


class OptionalMemoryPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_memory_failure_does_not_escape_chat_tail(self) -> None:
        with patch(
            "harness.core.runtime.asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError("vector offline")),
        ):
            await _remember_best_effort("Q: hello\nA: world", "session-1")

    async def test_basic_answer_is_saved_without_qdrant(self) -> None:
        settings = SimpleNamespace(qdrant_url="", qdrant_api_key="", embedding_api_key="key")
        with patch("harness.core.runtime.db.append_message", new=AsyncMock()) as append, patch(
            "harness.core.runtime.remember"
        ) as remember:
            await _persist_answer("session-1", "这是一个完整回答。", "你好", None, settings)
            append.assert_awaited_once_with("session-1", "assistant", "这是一个完整回答。")
            remember.assert_not_called()

    async def test_vector_failure_still_saves_answer(self) -> None:
        settings = SimpleNamespace(qdrant_url="url", qdrant_api_key="key", embedding_api_key="key")
        with patch("harness.core.runtime.db.append_message", new=AsyncMock()) as append, patch(
            "harness.core.runtime.asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError("vector offline")),
        ):
            await _persist_answer(
                "session-1", "这是一个足够完整的回答内容。", "你好", None, settings
            )
            append.assert_awaited_once()


class RunHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_history_is_redacted_before_persisting(self) -> None:
        event = {
            "event": "tool_call",
            "data": json.dumps(
                {
                    "type": "tool_call",
                    "tool": "http",
                    "inputs": {
                        "authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
                        "password": "plain-secret-value",
                    },
                }
            ),
        }
        with patch(
            "harness.routes.chat.db.append_run_event",
            new=AsyncMock(),
        ) as append:
            await _record_runtime_event("session-1", event)

        append.assert_awaited_once()
        persisted = append.await_args.args[2]
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", str(persisted))
        self.assertNotIn("plain-secret-value", str(persisted))
        self.assertIn("[REDACTED:CREDENTIAL]", str(persisted))

    async def test_phase_is_archived_broadcast_and_upserted_in_order(self) -> None:
        event = {
            "event": "phase",
            "data": json.dumps({"type": "phase", "id": "agent", "status": "running"}),
        }
        with (
            patch("harness.routes.chat.db.append_run_event", new=AsyncMock()) as append,
            patch("harness.routes.chat.db.upsert_phase", new=AsyncMock()) as upsert,
            patch("harness.routes.chat.event_bus.publish", new=AsyncMock()) as publish,
        ):
            await _record_runtime_event("session-1", event)

        append.assert_awaited_once()
        publish.assert_awaited_once()
        upsert.assert_awaited_once_with("agent", "session-1", event_data := json.loads(event["data"]))
        self.assertEqual(event_data["status"], "running")

    async def test_disconnected_chat_closes_runtime_and_persists_terminal_events(self) -> None:
        closed = asyncio.Event()

        async def stream_events(*_args, **_kwargs):
            try:
                yield {
                    "event": "phase",
                    "data": json.dumps(
                        {"type": "phase", "id": "agent:worker", "status": "running"}
                    ),
                }
                await asyncio.Future()
            finally:
                closed.set()

        with (
            patch("harness.routes.chat.db.get_session", new=AsyncMock(return_value=object())),
            patch("harness.routes.chat._runtime.stream_events", side_effect=stream_events),
            patch("harness.routes.chat._record_runtime_event", new=AsyncMock()) as record,
        ):
            from harness.app.schemas import ChatRequest
            from harness.routes.chat import chat

            response = await chat(ChatRequest(message="hello", session_id="session-1"), {})
            iterator = response.body_iterator
            await anext(iterator)  # session
            await anext(iterator)  # running phase
            waiting = asyncio.create_task(anext(iterator))
            await asyncio.sleep(0)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting

        self.assertTrue(closed.is_set())
        events = [call.args[1] for call in record.await_args_list]
        phase_payloads = [
            json.loads(event["data"]) for event in events if event["event"] == "phase"
        ]
        self.assertTrue(
            any(
                phase["id"] == "agent:worker" and phase["status"] == "failed"
                for phase in phase_payloads
            )
        )
        self.assertTrue(any(event["event"] == "worker_end" for event in events))

    async def test_subagent_worker_end_does_not_hide_disconnect_failure(self) -> None:
        async def stream_events(*_args, **_kwargs):
            yield {
                "event": "worker_end",
                "data": json.dumps(
                    {
                        "type": "worker_end",
                        "worker": "researcher",
                        "status": "ok",
                        "summary": "done",
                        "task_id": "sub-1",
                    }
                ),
            }
            await asyncio.Future()

        with (
            patch("harness.routes.chat.db.get_session", new=AsyncMock(return_value=object())),
            patch("harness.routes.chat._runtime.stream_events", side_effect=stream_events),
            patch("harness.routes.chat._record_runtime_event", new=AsyncMock()) as record,
        ):
            from harness.app.schemas import ChatRequest
            from harness.routes.chat import chat

            response = await chat(ChatRequest(message="hello", session_id="session-1"), {})
            iterator = response.body_iterator
            await anext(iterator)  # session
            await anext(iterator)  # sub-agent worker_end
            await iterator.aclose()

        root_end_events = [
            json.loads(call.args[1]["data"])
            for call in record.await_args_list
            if call.args[1]["event"] == "worker_end"
        ]
        self.assertTrue(
            any(event["task_id"] == "agent" and event["status"] == "failed" for event in root_end_events)
        )


class ApprovalHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_approval_is_persisted_to_audit_history(self) -> None:
        with patch(
            "harness.security.approvals.event_bus.publish",
            new=AsyncMock(),
        ), patch(
            "harness.security.approvals.db.save_approval_history",
            new=AsyncMock(),
        ), patch(
            "harness.security.approvals.append_audit",
            new=AsyncMock(return_value="f" * 64),
        ) as append, patch(
            "harness.security.approvals.db.mark_approval_audited",
            new=AsyncMock(),
        ) as mark:
            allowed = await request_approval(
                "session-1",
                "shell",
                "执行命令",
                risk="high",
                risk_source="derived",
                target="./release.sh",
                scope="本机",
                impact="写入文件",
                timeout=0.001,
            )

        self.assertFalse(allowed)
        self.assertEqual(list_pending(), [])
        append.assert_awaited_once()
        self.assertEqual(append.await_args.args[0], "tool_approval")
        self.assertEqual(append.await_args.kwargs["decision"], "expired")
        detail = append.await_args.kwargs["detail"]
        self.assertEqual(detail["tool_name"], "shell")
        self.assertTrue(detail["decision_id"])
        self.assertTrue(detail["requested_at"])
        self.assertTrue(detail["expires_at"])
        mark.assert_awaited_once()

    async def test_failed_audit_is_compensated_from_persistent_history(self) -> None:
        row = SimpleNamespace(
            decision_id="decision-1",
            call_id="call-1",
            tool_name="shell",
            session_id="session-1",
            actor="human",
            decision="approved",
            risk="high",
            risk_source="derived",
            target="./release.sh",
            scope="本机",
            impact="写入文件",
            message="执行发布脚本",
            requested_at="2026-09-15T00:00:00+00:00",
            expires_at="2026-09-15T00:05:00+00:00",
        )
        with patch(
            "harness.routes.chat.db.list_unaudited_approvals",
            new=AsyncMock(return_value=[row]),
        ), patch(
            "harness.routes.chat.query_audit",
            new=AsyncMock(return_value=[]),
        ), patch(
            "harness.routes.chat.append_audit",
            new=AsyncMock(return_value="a" * 64),
        ) as append, patch(
            "harness.routes.chat.db.mark_approval_audited",
            new=AsyncMock(),
        ) as mark:
            await _retry_approval_audits()

        append.assert_awaited_once()
        self.assertEqual(append.await_args.kwargs["decision"], "approved")
        mark.assert_awaited_once_with("decision-1", "a" * 64)

    async def test_decision_does_not_release_tool_when_history_write_fails(self) -> None:
        with patch(
            "harness.security.approvals.event_bus.publish",
            new=AsyncMock(),
        ):
            waiting = asyncio.create_task(
                request_approval("session-safe", "shell", "执行命令", timeout=1.0)
            )
            await asyncio.sleep(0)
            call_id = next(item["call_id"] for item in list_pending() if item["session_id"] == "session-safe")

            with patch(
                "harness.routes.chat.db.save_approval_history",
                new=AsyncMock(side_effect=RuntimeError("db unavailable")),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await submit_approval_decision(
                        call_id,
                        ApprovalDecision(approved=True),
                        {},
                    )

            self.assertEqual(caught.exception.status_code, 503)
            self.assertTrue(any(item["call_id"] == call_id for item in list_pending()))
            with patch(
                "harness.routes.chat.db.save_approval_history",
                new=AsyncMock(),
            ), patch(
                "harness.routes.chat.append_audit",
                new=AsyncMock(return_value="a" * 64),
            ), patch(
                "harness.routes.chat.db.mark_approval_audited",
                new=AsyncMock(),
            ):
                result = await submit_approval_decision(
                    call_id,
                    ApprovalDecision(approved=False),
                    {},
                )
            self.assertTrue(result["ok"])
            self.assertFalse(await waiting)


class ArtifactContractTests(unittest.TestCase):
    def test_artifact_metadata_has_explicit_source_size_and_update_time(self) -> None:
        now = datetime.now(UTC)
        row = SimpleNamespace(
            id="artifact-1",
            engagement_id="eng-1",
            producer="legacy-producer",
            source_session_id="session-1",
            media_type="text/markdown",
            kind="report",
            sensitivity="internal",
            title="报告",
            evidence="你好",
            tags='["g3"]',
            vault_ref="",
            severity="info",
            status="open",
            created_at=now,
            updated_at=now,
        )

        payload = artifact_to_dict(row)

        self.assertEqual(payload["size_bytes"], len("你好".encode()))
        self.assertEqual(payload["source_session_id"], "session-1")
        self.assertEqual(payload["source_run_id"], "session-1")
        self.assertEqual(payload["media_type"], "text/markdown")
        self.assertEqual(payload["updated_at"], now.isoformat())

    def test_secret_artifact_never_exposes_content_but_keeps_size(self) -> None:
        row = SimpleNamespace(
            id="artifact-secret",
            engagement_id="eng-1",
            producer="session-1",
            source_session_id="session-1",
            media_type="text/plain",
            kind="note",
            sensitivity="secret",
            title="密钥",
            evidence="super-secret",
            tags="[]",
            vault_ref="secret://ref",
            severity="critical",
            status="open",
            created_at=None,
            updated_at=None,
        )

        payload = artifact_to_dict(row)

        self.assertEqual(payload["content"], "")
        self.assertEqual(payload["size_bytes"], len("super-secret"))

    def test_media_type_is_derived_from_kind_and_content(self) -> None:
        self.assertEqual(_media_type("report", "# Report"), "text/markdown")
        self.assertEqual(_media_type("scan_result", '{"ok": true}'), "application/json")
        self.assertEqual(_media_type("scan_result", "plain output"), "text/plain")


class WorkspaceTests(unittest.TestCase):
    def test_providers_and_file_tools_share_existing_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"VANTA_ROOT": tmp}):
            # macOS 的 /var 是 /private/var 符号链接；与生产代码一样比较真实路径。
            root = (Path(tmp) / "workspace").resolve()
            self.assertEqual(ensure_workspace(), root)
            self.assertTrue((root / "agents").is_dir())
            self.assertTrue((root / "skills").is_dir())
            self.assertEqual(get_provider("agent").root, root / "agents")
            self.assertEqual(get_provider("skill").root, root / "skills")
            self.assertEqual(_resolve_cwd(None), (str(root), None))
            self.assertEqual(_resolve_cwd("agents"), (str(root / "agents"), None))
            allowed, error = _sandbox_path(str(root / "agents"))
            self.assertEqual((allowed, error), (root / "agents", None))
            allowed_relative, relative_error = _sandbox_path("agents")
            self.assertEqual((allowed_relative, relative_error), (root / "agents", None))
            _, denied = _sandbox_path(tmp)
            self.assertIn("超出工作目录", denied or "")
            (root / "escape").symlink_to(Path(tmp))
            _, symlink_denied = _sandbox_path("escape")
            self.assertIn("超出工作目录", symlink_denied or "")

        # 连接/部署根切换后缓存不可继续指向已删除的旧目录。
        self.assertEqual(get_provider("agent").root, Path(get_settings().agents_dir))


class ShellBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_workspace_can_run_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"VANTA_ROOT": tmp}):
            root = ensure_workspace()
            result = await _exec_command("pwd", None, 2)
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.output.strip(), str(root))

    async def test_out_of_workspace_cwd_has_permission_denied_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"VANTA_ROOT": tmp}):
            ensure_workspace()
            result = await _exec_command("pwd", "/", 1)
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "PERMISSION_DENIED")


if __name__ == "__main__":
    unittest.main()
