"""客户端基础对话所依赖的后端降级与工作区回归。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harness.app.main import ensure_workspace
from harness.core.capabilities.memory import automatic_memory_available, recall_as_context
from harness.core.runtime import _persist_answer, _remember_best_effort
from harness.infra.settings import get_settings
from harness.providers import get_provider
from harness.routes.chat import _record_runtime_event
from harness.tools.builtin.cmd.file_ops import _sandbox_path
from harness.tools.builtin.cmd.shell import _exec_command, _resolve_cwd


class OptionalMemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_unconfigured_qdrant_is_skipped_without_vector_request(self) -> None:
        settings = SimpleNamespace(qdrant_url="", qdrant_api_key="", embedding_api_key="key")
        self.assertFalse(automatic_memory_available(settings))
        with patch("harness.core.capabilities.memory.get_settings", return_value=settings), patch(
            "harness.core.capabilities.memory.vector.search_memory"
        ) as search:
            self.assertEqual(recall_as_context("你好"), "")
            search.assert_not_called()

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
