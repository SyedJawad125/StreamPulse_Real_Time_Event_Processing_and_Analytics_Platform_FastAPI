# app/workers/event_queue.py
"""Bounded, thread-safe queue of event ids.

The queue is only a *dispatch hint*: PostgreSQL is the source of truth, and anything lost from memory is
re-dispatched from the database by the sweeper.
"""
from __future__ import annotations

import queue
import threading


class EventQueue:
    def __init__(self, maxsize: int) -> None:
        self._queue: queue.Queue[int] = queue.Queue(maxsize=maxsize)
        self._pending: set[int] = set()  # prevents the same event being queued twice
        self._lock = threading.Lock()

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

    def try_put(self, event_pk: int) -> bool:
        """Non-blocking enqueue. False when the queue is full or the event is already queued."""
        with self._lock:
            if event_pk in self._pending:
                return False
            try:
                self._queue.put_nowait(event_pk)
            except queue.Full:
                return False
            self._pending.add(event_pk)
            return True

    def get(self, timeout: float) -> int:
        """Blocking get; raises queue.Empty after `timeout` seconds."""
        event_pk = self._queue.get(timeout=timeout)
        with self._lock:
            self._pending.discard(event_pk)
        return event_pk

    def task_done(self) -> None:
        self._queue.task_done()
