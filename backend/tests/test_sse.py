import asyncio
import json

import pytest

from app.core.exceptions import ServiceUnavailableError
from app.services.event_broker import EventBroker, format_sse, sse_stream
from tests.helpers import ingest, make_user, auth_headers, wait_status

API = "/api/v1"


def parse_frames(raw: str) -> list[dict]:
    frames = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {}
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            elif ":" in line:
                k, v = line.split(":", 1)
                frame[k] = v.strip()
        frames.append(frame)
    return frames


def test_sse_frame_format():
    f = format_sse("event.processed", {"a": 1, "text": "line1\nline2"}, event_id=7)
    assert f.endswith("\n\n") and f.startswith("id: 7\nevent: event.processed\ndata: ")
    data_lines = [l for l in f.split("\n") if l.startswith("data:")]
    assert len(data_lines) == 1 and json.loads(data_lines[0][5:]) == {"a": 1, "text": "line1\nline2"}  # newline is escaped
    assert "id:" not in format_sse("x", {})


def test_broker_bounded_buffer_drops_oldest():
    broker = EventBroker(buffer_size=3, max_clients=2)
    sub = broker.subscribe()
    for i in range(5):
        broker.publish("t", {"n": i})
    assert sub.queue.qsize() == 3 and sub.dropped == 2
    assert [sub.queue.get_nowait()["n"] for _ in range(3)] == [2, 3, 4]  # newest kept


def test_broker_client_cap_and_unsubscribe():
    broker = EventBroker(buffer_size=2, max_clients=2)
    a, b = broker.subscribe(), broker.subscribe()
    with pytest.raises(ServiceUnavailableError):
        broker.subscribe()
    broker.unsubscribe(a)
    broker.unsubscribe(a)  # idempotent
    assert broker.client_count == 1
    broker.subscribe()
    assert broker.client_count == 2


async def test_stream_generator_events_heartbeat_overflow_and_cleanup_on_disconnect():
    broker = EventBroker(buffer_size=2, max_clients=5)
    sub = broker.subscribe()
    state = {"disconnected": False}

    async def is_disconnected():
        return state["disconnected"]

    gen = sse_stream(broker, sub, is_disconnected, heartbeat_seconds=0.15, poll_seconds=0.05)
    out = [await gen.__anext__(), await gen.__anext__()]
    assert out[0] == "retry: 3000\n\n" and "event: connected" in out[1]

    broker.publish("event.processed", {"event_id": "e1"})
    frame = await gen.__anext__()
    assert "event: event.processed" in frame and '"event_id":"e1"' in frame and frame.startswith("id: ")

    assert await gen.__anext__() == ": heartbeat\n\n"  # idle -> heartbeat comment

    for i in range(4):  # overflow the 2-slot buffer
        broker.publish("t", {"n": i})
    assert "event: overflow" in await gen.__anext__()
    assert '"n":2' in await gen.__anext__()

    state["disconnected"] = True
    assert [x async for x in gen] == []  # generator ends cleanly after disconnect
    assert broker.client_count == 0  # unsubscribed once the client is gone


async def test_stream_generator_cleans_up_when_cancelled():
    broker = EventBroker()
    sub = broker.subscribe()

    async def never():
        return False

    gen = sse_stream(broker, sub, never, heartbeat_seconds=10)
    await gen.__anext__()
    await gen.aclose()  # what Starlette does when the connection drops
    assert broker.client_count == 0


async def run_asgi_stream(app, path, headers=None, run_for=0.6, publish=None):
    """Drive the real ASGI app with a streaming request and a client that disconnects after `run_for` seconds."""
    sent: list[dict] = []
    disconnect = asyncio.Event()

    async def receive():
        if not disconnect.is_set():
            await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "path": path.split("?")[0],
             "raw_path": path.split("?")[0].encode(), "query_string": path.partition("?")[2].encode(), "root_path": "",
             "scheme": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             "client": ("127.0.0.1", 5555), "server": ("test", 80), "app": app}
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.sleep(run_for / 2)
    if publish:
        publish()
    await asyncio.sleep(run_for / 2)
    disconnect.set()
    await asyncio.wait_for(task, 5)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    return start, body


async def test_stream_endpoint_requires_auth_and_permission(h, viewer_headers):
    assert (await h.client.get(f"{API}/events/stream")).status_code == 401
    assert (await h.client.get(f"{API}/events/stream", params={"ticket": "bogus"})).status_code == 401
    await make_user(h, "nobody", [])
    nh = await auth_headers(h, "nobody")
    assert (await h.client.get(f"{API}/events/stream", headers=nh)).status_code == 403
    assert (await h.client.post(f"{API}/events/stream-ticket", headers=nh)).status_code == 403
    assert (await h.client.post(f"{API}/events/stream-ticket")).status_code == 401


async def test_stream_endpoint_end_to_end_with_ticket_and_cleanup(h, viewer_headers, key_headers):
    t = (await h.client.post(f"{API}/events/stream-ticket", headers=viewer_headers)).json()
    assert t["expires_in_seconds"] == h.settings.stream_ticket_ttl_seconds and len(t["ticket"]) > 20
    pub = lambda: h.app.state.broker.publish("event.processed", {"event_id": "live-1", "status": "PROCESSED"})
    start, body = await run_asgi_stream(h.app, f"{API}/events/stream?ticket={t['ticket']}", publish=pub)
    assert start["status"] == 200
    hdrs = {k.decode(): v.decode() for k, v in start["headers"]}
    assert hdrs["content-type"].startswith("text/event-stream") and hdrs["cache-control"] == "no-cache"
    frames = parse_frames(body)
    assert any(f.get("event") == "connected" for f in frames)
    live = [f for f in frames if f.get("event") == "event.processed"]
    assert live and json.loads(live[0]["data"])["event_id"] == "live-1"
    assert any(f.get("comment") == "heartbeat" for f in frames)
    assert h.app.state.broker.client_count == 0  # disconnected client was cleaned up

    reuse = await h.client.get(f"{API}/events/stream", params={"ticket": t["ticket"]})
    assert reuse.status_code == 401  # tickets are single-use


async def test_stream_with_bearer_receives_real_pipeline_notifications(h, admin_headers, key_headers):
    async def trigger():
        await asyncio.sleep(0.2)
        await ingest(h, key_headers, event_id="pipeline-1")

    trig = asyncio.create_task(trigger())
    _, body = await run_asgi_stream(h.app, f"{API}/events/stream", headers=admin_headers, run_for=1.5)
    await trig
    kinds = [f.get("event") for f in parse_frames(body)]
    assert {"event.received", "event.processing", "event.processed"} <= set(kinds)
    assert "pipeline-1" in body and "payload" not in body  # notifications never carry event payloads
    assert h.app.state.broker.client_count == 0


async def test_stream_capacity_limit():
    from tests.helpers import running_app
    async with running_app(sse_max_clients=1) as h:
        await make_user(h, "admin", ["ADMIN"]); ah = await auth_headers(h, "admin")
        h.app.state.broker.subscribe()  # occupy the only slot
        r = await h.client.get(f"{API}/events/stream", headers=ah)
        assert r.status_code == 503 and r.json()["error"]["code"] == "STREAM_CAPACITY"
