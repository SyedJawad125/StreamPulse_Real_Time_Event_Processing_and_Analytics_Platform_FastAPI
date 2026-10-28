# app/middleware/body_limit.py
"""Reject oversized request bodies with 413 (checks Content-Length and streamed bytes)."""
from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, send: Send) -> None:
        body = json.dumps({"detail": f"Request body exceeds {self.max_bytes} bytes", "code": "PAYLOAD_TOO_LARGE",
                           "request_id": scope.get("state", {}).get("request_id")}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length and length.isdigit() and int(length) > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes and not rejected:
                    # FastAPI turns exceptions raised while reading the body into a 400, so answer 413 here,
                    # then tell the app the client went away and drop whatever it tries to send afterwards.
                    rejected = True
                    if not started:
                        await self._reject(scope, send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)
