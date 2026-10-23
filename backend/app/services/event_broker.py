"""In-process pub/sub for Server-Sent Events.

Notifications are best-effort and NOT durable: clients that miss messages must
re-query the REST API. Every subscriber has a bounded buffer; when it overflows
the oldest message is dropped and the client is told via an `overflow` event.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from app.core.exceptions import ServiceUnavailableError


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[dict[str, Any]]
    dropped: int = 0
    connected_at: float = field(default_factory=time.monotonic)


class EventBroker:
    def __init__(self, buffer_size: int = 100, max_clients: int = 100) -> None:
        self.buffer_size = buffer_size
        self.max_clients = max_clients
        self._subs: set[Subscriber] = set()
        self._ids = itertools.count(1)

    @property
    def client_count(self) -> int:
        return len(self._subs)

    def subscribe(self) -> Subscriber:
        if len(self._subs) >= self.max_clients:
            raise ServiceUnavailableError("Too many live-stream clients", code="STREAM_CAPACITY")
        sub = Subscriber(queue=asyncio.Queue(maxsize=self.buffer_size))
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        message = {
            "id": next(self._ids),
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        for sub in tuple(self._subs):
            try:
                sub.queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    sub.queue.get_nowait()  # drop the oldest to bound memory
                except asyncio.QueueEmpty:  # pragma: no cover - defensive
                    pass
                sub.dropped += 1
                sub.queue.put_nowait(message)


def format_sse(event: str, data: dict[str, Any], event_id: int | str | None = None) -> str:
    """Format one SSE frame. JSON never contains raw newlines, so a single data line is valid."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'), default=str)}")
    return "\n".join(lines) + "\n\n"


async def sse_stream(
    broker: EventBroker,
    sub: Subscriber,
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_seconds: float,
    poll_seconds: float = 1.0,
) -> AsyncIterator[str]:
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
