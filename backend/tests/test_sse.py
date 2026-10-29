import asyncio
import json

import pytest

from app.exceptions import AppError
from app.workers.event_broker import EventBroker, TicketStore, format_sse, sse_stream
from tests.helpers import EV, K, R, ingest, login_headers, make_user

S = "/api/events/v1/stream/"
T = "/api/events/v1/stream-ticket/"


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
    assert len(data_lines) == 1 and json.loads(data_lines[0][5:]) == {"a": 1, "text": "line1\nline2"}
    assert "id:" not in format_sse("x", {})


async def test_broker_bounded_buffer_drops_oldest():
    broker = EventBroker(buffer_size=3, max_clients=2)
    sub = broker.subscribe()
    for i in range(5):
        broker.publish("t", {"n": i})
    await asyncio.sleep(0.05)  # delivery is scheduled onto the subscriber's loop
    assert sub.queue.qsize() == 3 and sub.dropped == 2
    assert [sub.queue.get_nowait()["n"] for _ in range(3)] == [2, 3, 4]  # newest kept


async def test_broker_client_cap_and_unsubscribe():
    broker = EventBroker(buffer_size=2, max_clients=2)
    a, _b = broker.subscribe(), broker.subscribe()
    with pytest.raises(AppError):
        broker.subscribe()
    broker.unsubscribe(a)
    broker.unsubscribe(a)  # idempotent
    assert broker.client_count == 1
    broker.subscribe()
    assert broker.client_count == 2


async def test_broker_publish_from_other_threads_is_safe():
    broker = EventBroker(buffer_size=500, max_clients=2)
    sub = broker.subscribe()
    await asyncio.gather(*[asyncio.to_thread(lambda i=i: [broker.publish("t", {"n": i * 10 + j}) for j in range(10)])
                           for i in range(10)])
    await asyncio.sleep(0.1)
    assert sub.queue.qsize() == 100 and sub.dropped == 0


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
    await asyncio.sleep(0.05)
    assert "event: overflow" in await gen.__anext__()
    assert '"n":2' in await gen.__anext__()
    state["disconnected"] = True
    assert [x async for x in gen] == []
    assert broker.client_count == 0


async def test_stream_generator_cleans_up_when_closed():
    broker = EventBroker()
    sub = broker.subscribe()

    async def never():
        return False

    gen = sse_stream(broker, sub, never, heartbeat_seconds=10)
    await gen.__anext__()
    await gen.aclose()  # what Starlette does when the connection drops
    assert broker.client_count == 0


def test_ticket_store_single_use_and_expiry():
    store = TicketStore()
    t = store.issue(5, 30)
    assert store.consume(t) == 5 and store.consume(t) is None  # single use
    assert store.consume("unknown") is None
    assert store.consume(store.issue(5, -1)) is None  # expired


async def run_asgi_stream(app, path, headers=None, run_for=0.6, publish=None):
    """Drive the real ASGI app with a streaming request; the client 'disconnects' after `run_for` seconds."""
    sent: list[dict] = []
    disconnect = asyncio.Event()

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "path": path.split("?")[0], "raw_path": path.split("?")[0].encode(), "root_path": "", "scheme": "http",
             "query_string": path.partition("?")[2].encode(),
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             "client": ("127.0.0.1", 5555), "server": ("test", 80), "app": app}
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.sleep(run_for / 2)
    if publish:
        await publish()
    await asyncio.sleep(run_for / 2)
    disconnect.set()
    await asyncio.wait_for(task, 5)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    return start, body


def test_stream_endpoint_requires_auth_and_permission(client, admin_headers):
    assert client.get(S).status_code == 401
    r = client.get(S, params={"ticket": "bogus"})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_TICKET"
    client.post(R, headers=admin_headers, json={"name": "Empty", "description": "d", "code": "empty"})
    make_user("nobody@example.com", "empty")
    nh = login_headers(client, "nobody@example.com")
    assert client.get(S, headers=nh).status_code == 403
    assert client.post(T, headers=nh).status_code == 403 and client.post(T).status_code == 401
    # a ticket is only an introduction: the user's permission is re-checked when it is redeemed
    viewer_id = make_user("v2@example.com", "viewer")
    vh = login_headers(client, "v2@example.com")
    ticket = client.post(T, headers=vh).json()["ticket"]
    client.patch(f"/api/user/{viewer_id}", headers=admin_headers, json={"is_active": False})
    assert client.get(S, params={"ticket": ticket}).json()["code"] == "ACCOUNT_DISABLED"


async def test_stream_endpoint_end_to_end_with_ticket_and_cleanup(client, viewer_headers):
    t = (await asyncio.to_thread(client.post, T, headers=viewer_headers)).json()
    assert t["expires_in_seconds"] == 30 and len(t["ticket"]) > 20

    async def pub():
        client.app.state.broker.publish("event.processed", {"event_id": "live-1", "status": "PROCESSED"})

    start, body = await run_asgi_stream(client.app, f"{S}?ticket={t['ticket']}", publish=pub)
    assert start["status"] == 200
    hdrs = {k.decode(): v.decode() for k, v in start["headers"]}
    assert hdrs["content-type"].startswith("text/event-stream") and hdrs["cache-control"] == "no-cache"
    frames = parse_frames(body)
    assert any(f.get("event") == "connected" for f in frames)
    live = [f for f in frames if f.get("event") == "event.processed"]
    assert live and json.loads(live[0]["data"])["event_id"] == "live-1"
    assert any(f.get("comment") == "heartbeat" for f in frames)
    assert client.app.state.broker.client_count == 0  # the disconnected client was cleaned up
    reuse = await asyncio.to_thread(client.get, S, params={"ticket": t["ticket"]})
    assert reuse.status_code == 401  # tickets are single use


async def test_stream_with_bearer_receives_real_pipeline_notifications(client, admin_headers, key_headers):
    async def trigger():
        await asyncio.to_thread(ingest, client, key_headers, event_id="pipeline-1")

    _, body = await run_asgi_stream(client.app, S, headers=admin_headers, run_for=1.5, publish=trigger)
    kinds = [f.get("event") for f in parse_frames(body)]
    assert {"event.received", "event.processing", "event.processed"} <= set(kinds)
    assert "pipeline-1" in body and "payload" not in body  # notifications never carry event payloads
    assert client.app.state.broker.client_count == 0


def test_stream_capacity_limit(client, admin_headers, monkeypatch):
    monkeypatch.setattr(client.app.state.broker, "max_clients", 0)
    r = client.get(S, headers=admin_headers)
    assert r.status_code == 503 and r.json()["code"] == "STREAM_CAPACITY"
