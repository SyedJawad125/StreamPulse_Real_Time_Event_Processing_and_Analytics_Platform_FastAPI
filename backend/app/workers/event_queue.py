"""Bounded in-process queue of event primary keys.

The queue is only a *dispatch hint*: PostgreSQL is the source of truth, and
anything lost from memory is re-dispatched from the database by the sweeper.
"""
from __future__ import annotations

import asyncio
import uuid


class EventQueue:
    def __init__(self, maxsize: int) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue(maxsize=maxsize)
        self._pending: set[uuid.UUID] = set()  # prevents the same event being queued twice

    @property
    def capacity(self) -> int:
        return self._queue.maxsize

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def free(self) -> int:
        return self.capacity - self.size

    def full(self) -> bool:
        return self._queue.full()

    def try_put(self, event_pk: uuid.UUID) -> bool:
        """Non-blocking enqueue. False when full or already queued."""
        if event_pk in self._pending:
            return False
        try:
            self._queue.put_nowait(event_pk)
        except asyncio.QueueFull:
            return False
        self._pending.add(event_pk)
        return True

    async def get(self) -> uuid.UUID:
        event_pk = await self._queue.get()
        self._pending.discard(event_pk)
        return event_pk

    def task_done(self) -> None:
        self._queue.task_done()
