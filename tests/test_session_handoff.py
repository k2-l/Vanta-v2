"""最新会话重构中检查点、读取边界与单次更新的回归测试。"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from harness.app.schemas import CompressCommitRequest, SessionUpdate
from harness.core.context.summarize import compact_session_history
from harness.infra import db
from harness.routes import sessions


class _FakeDbSession:
    def __init__(self, *, latest=None, rows=()):
        self.latest = latest
        self.rows = list(rows)
        self.statements = []
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.latest

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(
            scalar_one_or_none=lambda: self.rows[0] if self.rows else None,
            scalars=lambda: SimpleNamespace(all=lambda: self.rows),
            scalar=lambda: self.latest,
        )


class SessionHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_compaction_reserves_reasoning_budget_and_rejects_empty_output(self):
        empty_response = SimpleNamespace(content="")
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=empty_response))
        with patch(
            "harness.core.context.summarize.build_chat_model", return_value=model
        ) as build:
            with self.assertRaisesRegex(RuntimeError, "空摘要"):
                await compact_session_history(
                    "用户：测试",
                    model_name="reasoning-model",
                    provider="anthropic",
                    max_tokens=128,
                )
        self.assertEqual(build.call_args.kwargs["max_tokens"], 4096)

    async def test_run_summaries_keep_status_priority_and_duration(self):
        started = datetime(2026, 9, 15, 12, tzinfo=UTC)
        finished = started + timedelta(seconds=5)
        scenarios = [
            (0, 0, 0, "queued", None, None),
            (2, 1, 1, "running", None, 5000),
            (2, 0, 1, "failed", finished, 5000),
            (2, 0, 0, "completed", finished, 5000),
        ]
        rows = [
            SimpleNamespace(
                id=str(index),
                title="运行",
                created_at=started,
                updated_at=finished,
                steps=steps,
                active=active,
                failed=failed,
                started_at=started if steps else None,
                phase_updated_at=finished,
            )
            for index, (steps, active, failed, *_expected) in enumerate(scenarios)
        ]

        class RunDbSession(_FakeDbSession):
            async def execute(self, statement):
                self.statements.append(statement)
                return rows

        fake = RunDbSession()
        with (
            patch.object(db, "session_factory", return_value=lambda: fake),
            patch.object(db, "_now", return_value=finished),
        ):
            summaries = await db.list_run_summaries()
        for summary, (_, _, _, status, finished_at, duration_ms) in zip(
            summaries, scenarios, strict=True
        ):
            self.assertEqual(summary["status"], status)
            self.assertEqual(summary["finished_at"], finished_at)
            self.assertEqual(summary["duration_ms"], duration_ms)

    async def test_list_limits_are_clamped_before_database_queries(self):
        now = datetime.now(UTC)
        row = SimpleNamespace(id="s", title="会话", created_at=now, updated_at=now)
        with patch.object(sessions.db, "list_sessions", new=AsyncMock(return_value=[row])) as query:
            await sessions.list_sessions(100_000)
            query.assert_awaited_once_with(limit=200)
        with (
            patch.object(sessions.db, "get_session", new=AsyncMock(return_value=row)),
            patch.object(sessions.db, "recent_messages", new=AsyncMock(return_value=[])) as query,
        ):
            await sessions.list_messages("s", 100_000)
            query.assert_awaited_once_with("s", n=500)

    async def test_title_update_returns_row_in_one_query(self):
        now = datetime.now(UTC)
        row = SimpleNamespace(id="s", title="新标题", created_at=now, updated_at=now)
        fake = _FakeDbSession(rows=[row])
        with patch.object(db, "session_factory", return_value=lambda: fake):
            updated = await db.update_title("s", "新标题")
        self.assertIs(updated, row)
        self.assertEqual(len(fake.statements), 1)
        self.assertIn("RETURNING", str(fake.statements[0]))
        fake.commit.assert_awaited_once()
        with (
            patch.object(sessions.db, "update_title", new=AsyncMock(return_value=row)),
            patch.object(sessions.db, "get_session", new=AsyncMock()) as lookup,
        ):
            await sessions.patch_session("s", SessionUpdate(title="新标题"))
            lookup.assert_not_awaited()

    async def test_compaction_checkpoint_never_exceeds_latest_message(self):
        latest = datetime(2026, 9, 15, 12, tzinfo=UTC)
        fake = _FakeDbSession(latest=latest)
        with patch.object(db, "session_factory", return_value=lambda: fake):
            await db.set_compaction("s", "摘要", latest + timedelta(days=1))
        update_stmt = fake.statements[1]
        self.assertEqual(update_stmt.compile().params["compacted_upto"], latest)
        fake.commit.assert_awaited_once()

        empty = _FakeDbSession()
        with patch.object(db, "session_factory", return_value=lambda: empty):
            with self.assertRaises(ValueError):
                await db.set_compaction("s", "摘要", latest)
        empty.commit.assert_not_awaited()

    async def test_message_windows_use_id_to_break_timestamp_ties(self):
        latest = datetime(2026, 9, 15, 12, tzinfo=UTC)
        rows = [SimpleNamespace(id="b"), SimpleNamespace(id="a")]
        recent = _FakeDbSession(rows=rows)
        with patch.object(db, "session_factory", return_value=lambda: recent):
            await db.recent_messages("s", n=2)
        self.assertIn(
            "ORDER BY messages.created_at DESC, messages.id DESC", str(recent.statements[0])
        )

        fallback = _FakeDbSession(rows=rows)
        with patch.object(db, "session_factory", return_value=lambda: fallback):
            await db.messages_after_checkpoint("s", fallback_n=2)
        self.assertIn(
            "ORDER BY messages.created_at DESC, messages.id DESC", str(fallback.statements[1])
        )

        checkpointed = _FakeDbSession(latest=latest, rows=rows)
        with patch.object(db, "session_factory", return_value=lambda: checkpointed):
            await db.messages_after_checkpoint("s")
        self.assertIn(
            "ORDER BY messages.created_at ASC, messages.id ASC", str(checkpointed.statements[1])
        )

        interrupted = _FakeDbSession()
        with patch.object(db, "session_factory", return_value=lambda: interrupted):
            await db.mark_interrupted_turns()
        self.assertIn(
            "ORDER BY messages.created_at DESC, messages.id DESC",
            str(interrupted.statements[0]),
        )

    async def test_preview_stops_stream_and_closes_it_at_token_budget(self):
        upto = datetime(2026, 9, 15, 12, tzinfo=UTC)
        row = SimpleNamespace(id="s")
        closed = False
        consumed = 0

        oldest = upto - timedelta(minutes=2)

        async def source(_session_id, _after, _upto):
            nonlocal closed, consumed
            try:
                for index, content in enumerate(("old", "new", "ignored")):
                    consumed += 1
                    yield SimpleNamespace(
                        content=content,
                        role="user",
                        created_at=oldest + timedelta(minutes=index),
                    )
            finally:
                closed = True

        settings = SimpleNamespace(
            compaction_input_max_tokens=3,
            model_low="model",
            model_low_provider="provider",
            summarize_max_tokens=100,
        )
        with (
            patch.object(sessions.db, "get_session", new=AsyncMock(return_value=row)),
            patch.object(sessions.db, "latest_message_at", new=AsyncMock(return_value=upto)),
            patch.object(sessions.db, "uncompacted_messages_upto", side_effect=source),
            patch.object(sessions.db, "get_compaction", new=AsyncMock(return_value=("", None))),
            patch.object(sessions, "get_settings", return_value=settings),
            patch.object(sessions, "count_tokens", side_effect=len),
            patch.object(sessions, "resolve_provider", return_value=object()),
            patch.object(
                sessions, "compact_session_history", new=AsyncMock(return_value="摘要")
            ) as summarize,
        ):
            preview = await sessions.compress_preview("s")
        self.assertEqual(consumed, 2)
        self.assertTrue(closed)
        self.assertEqual(preview.messages, 1)
        self.assertEqual(preview.upto, oldest)
        self.assertIn("old", summarize.await_args.args[0])
        self.assertNotIn("new", summarize.await_args.args[0])

    async def test_preview_keeps_timestamp_ties_together(self):
        boundary = datetime(2026, 9, 15, 12, tzinfo=UTC)

        async def source(_session_id, _after, _upto):
            yield SimpleNamespace(content="a", role="user", created_at=boundary)
            yield SimpleNamespace(content="b", role="assistant", created_at=boundary)
            yield SimpleNamespace(
                content="c", role="user", created_at=boundary + timedelta(seconds=1)
            )

        settings = SimpleNamespace(
            compaction_input_max_tokens=1,
            model_low="model",
            model_low_provider="provider",
            summarize_max_tokens=100,
        )
        with (
            patch.object(sessions.db, "get_session", new=AsyncMock(return_value=object())),
            patch.object(
                sessions.db,
                "latest_message_at",
                new=AsyncMock(return_value=boundary + timedelta(seconds=1)),
            ),
            patch.object(sessions.db, "uncompacted_messages_upto", side_effect=source),
            patch.object(sessions.db, "get_compaction", new=AsyncMock(return_value=("", None))),
            patch.object(sessions, "get_settings", return_value=settings),
            patch.object(sessions, "count_tokens", side_effect=len),
            patch.object(sessions, "resolve_provider", return_value=object()),
            patch.object(
                sessions, "compact_session_history", new=AsyncMock(return_value="摘要")
            ) as summarize,
        ):
            preview = await sessions.compress_preview("s")

        self.assertEqual(preview.messages, 2)
        self.assertEqual(preview.upto, boundary)
        self.assertIn("a", summarize.await_args.args[0])
        self.assertIn("b", summarize.await_args.args[0])
        self.assertNotIn("c", summarize.await_args.args[0])

    async def test_commit_rejects_empty_history(self):
        with (
            patch.object(sessions.db, "get_session", new=AsyncMock(return_value=object())),
            patch.object(
                sessions.db, "set_compaction", new=AsyncMock(side_effect=ValueError("没有消息"))
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await sessions.compress_commit(
                    "s", CompressCommitRequest(summary="摘要", upto=datetime.now(UTC))
                )
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
