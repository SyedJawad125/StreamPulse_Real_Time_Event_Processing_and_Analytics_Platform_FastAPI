# app/workers/event_broker.py
"""In-process pub/sub for Server-Sent Events (thread-safe publish, asyncio subscribers).

Notifications are best-effort and NOT durable: clients that miss messages must re-query the REST API. Every
subscriber has a bounded buffer; when it overflows the oldest message is dropped and the client is told via an
`overflow` event.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from app.exceptions import AppError


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    dropped: int = 0
    connected_at: float = field(default_factory=time.monotonic)


class EventBroker:
    def __init__(self, buffer_size: int = 100, max_clients: int = 50) -> None:
        self.buffer_size = buffer_size
        self.max_clients = max_clients
        self._subs: set[Subscriber] = set()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def subscribe(self) -> Subscriber:
        """Must be called from the event loop that will consume the stream."""
        with self._lock:
            if len(self._subs) >= self.max_clients:
                raise AppError(503, "Too many live-stream clients", "STREAM_CAPACITY")
            sub = Subscriber(queue=asyncio.Queue(maxsize=self.buffer_size), loop=asyncio.get_running_loop())
            self._subs.add(sub)
            return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.discard(sub)

    @staticmethod
    def _deliver(sub: Subscriber, message: dict[str, Any]) -> None:  # runs on the subscriber's loop thread
        try:
            sub.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                sub.queue.get_nowait()  # drop the oldest to keep memory bounded
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
            sub.dropped += 1
            sub.queue.put_nowait(message)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Safe to call from any thread."""
        message = {"id": next(self._ids), "type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **data}
        with self._lock:
            subs = tuple(self._subs)
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(self._deliver, sub, message)
            except RuntimeError:  # that loop has been closed
                self.unsubscribe(sub)


def format_sse(event: str, data: dict[str, Any], event_id: int | str | None = None) -> str:
    """One SSE frame. JSON contains no raw newlines, so a single data line is valid."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'), default=str)}")
    return "\n".join(lines) + "\n\n"


async def sse_stream(broker: EventBroker, sub: Subscriber, is_disconnected: Callable[[], Awaitable[bool]],
                     heartbeat_seconds: float, poll_seconds: float = 1.0) -> AsyncIterator[str]:
    """Yield SSE frames until the client disconnects; always unsubscribes on exit."""
    try:
        yield "retry: 3000\n\n"
        yield format_sse("connected", {"heartbeat_seconds": heartbeat_seconds})
        last_sent = time.monotonic()
        while True:
            if await is_disconnected():
                break
            try:
                message = await asyncio.wait_for(sub.queue.get(), timeout=min(poll_seconds, heartbeat_seconds))
            except asyncio.TimeoutError:
                if time.monotonic() - last_sent >= heartbeat_seconds:
                    yield ": heartbeat\n\n"
                    last_sent = time.monotonic()
                continue
            if sub.dropped:
                yield format_sse("overflow", {"dropped": sub.dropped})
                sub.dropped = 0
            yield format_sse(message["type"], message, event_id=message["id"])
            last_sent = time.monotonic()
    finally:
        broker.unsubscribe(sub)


class TicketStore:
    """Short-lived, single-use tickets so browsers' EventSource (which cannot send an Authorization header)
    can open the live stream without putting a JWT in the URL. Per-process, thread-safe."""

    MAX_OUTSTANDING = 10_000

    def __init__(self) -> None:
        self._tickets: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: int, ttl_seconds: float) -> str:
        import secrets
        now = time.monotonic()
        with self._lock:
            for t in [t for t, (_, exp) in self._tickets.items() if exp < now]:
                del self._tickets[t]
            if len(self._tickets) >= self.MAX_OUTSTANDING:
                raise AppError(503, "Too many outstanding stream tickets", "TICKET_CAPACITY")
            ticket = secrets.token_urlsafe(32)
            self._tickets[ticket] = (user_id, now + ttl_seconds)
            return ticket

    def consume(self, ticket: str) -> int | None:
        """Return the user id and invalidate the ticket (None if unknown/expired/already used)."""
        with self._lock:
            entry = self._tickets.pop(ticket, None)
        if not entry or entry[1] < time.monotonic():
            return None
        return entry[0]
