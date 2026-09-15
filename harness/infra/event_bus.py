"""In-memory session-scoped pub/sub for WebSocket Task status broadcasting.

Usage:
    async with event_bus.subscribe(session_id) as q:
        event = await q.get()

    await event_bus.publish(session_id, {"type": "phase", ...})
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[session_id].append(q)
        try:
            yield q
        finally:
            self._queues[session_id].remove(q)
            if not self._queues[session_id]:
                del self._queues[session_id]

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        for q in list(self._queues.get(session_id, [])):
            await q.put(event)

    def subscriber_count(self, session_id: str) -> int:
        return len(self._queues.get(session_id, []))


# Module-level singleton used by chat route and ws route.
event_bus = EventBus()
