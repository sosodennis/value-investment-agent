from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.client_debug.config import MAX_CLIENT_DEBUG_REQUEST_BYTES


class ClientDebugRequestSizeMiddleware:
    """Reject oversized client-debug requests before JSON parsing allocates them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_client_debug_post(scope):
            await self.app(scope, receive, send)
            return
        if self._declared_size_is_oversized(scope):
            await self._reject(send)
            return
        await self._receive_limited(scope, receive, send)

    @staticmethod
    def _is_client_debug_post(scope: Scope) -> bool:
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/v1/client-debug/events"
        )

    @staticmethod
    def _declared_size_is_oversized(scope: Scope) -> bool:
        raw_length = next(
            (
                value
                for key, value in scope.get("headers", [])
                if key.lower() == b"content-length"
            ),
            None,
        )
        if raw_length is None:
            return False
        try:
            return int(raw_length) > MAX_CLIENT_DEBUG_REQUEST_BYTES
        except ValueError:
            return False

    async def _receive_limited(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        received_bytes = 0
        oversized = False

        async def limited_receive() -> Message:
            nonlocal received_bytes, oversized
            if oversized:
                return {"type": "http.request", "body": b"", "more_body": False}

            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                oversized = received_bytes > MAX_CLIENT_DEBUG_REQUEST_BYTES
                if oversized:
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def limited_send(message: Message) -> None:
            if not oversized:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except ClientDisconnect:
            if not oversized:
                raise

        if oversized:
            await self._reject(send)

    @staticmethod
    async def _reject(send: Callable[[Message], Awaitable[None]]) -> None:
        body = b'{"detail":"client_debug_request_too_large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
