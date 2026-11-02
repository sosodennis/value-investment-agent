from __future__ import annotations

import pytest
from starlette.types import Message, Receive, Scope, Send

from src.client_debug.config import MAX_CLIENT_DEBUG_REQUEST_BYTES
from src.client_debug.interface.middleware import ClientDebugRequestSizeMiddleware


async def _noop_app(scope: dict[str, object], receive: object, send: object) -> None:
    raise AssertionError("oversized request should be rejected by middleware")


@pytest.mark.asyncio
async def test_client_debug_request_size_is_rejected_before_app() -> None:
    messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    middleware = ClientDebugRequestSizeMiddleware(_noop_app)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/client-debug/events",
        "headers": [
            (b"content-length", str(MAX_CLIENT_DEBUG_REQUEST_BYTES + 1).encode())
        ],
    }

    await middleware(scope, lambda: None, send)

    assert messages[0]["status"] == 413
    assert messages[1]["body"] == b'{"detail":"client_debug_request_too_large"}'


@pytest.mark.asyncio
async def test_client_debug_request_size_counts_streamed_body_without_content_length() -> (
    None
):
    messages: list[Message] = []
    received_chunks: list[bytes] = []
    incoming: list[Message] = [
        {
            "type": "http.request",
            "body": b"a" * MAX_CLIENT_DEBUG_REQUEST_BYTES,
            "more_body": True,
        },
        {"type": "http.request", "body": b"b", "more_body": False},
    ]

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            received_chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        messages.append(message)

    middleware = ClientDebugRequestSizeMiddleware(app)
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/client-debug/events",
        "headers": [],
    }

    await middleware(scope, receive, send)

    assert sum(map(len, received_chunks)) == MAX_CLIENT_DEBUG_REQUEST_BYTES
    assert messages[0]["status"] == 413
    assert messages[1]["body"] == b'{"detail":"client_debug_request_too_large"}'
