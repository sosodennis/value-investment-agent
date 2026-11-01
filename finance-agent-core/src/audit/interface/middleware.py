from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.shared.kernel.correlation import (
    normalize_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)


class CorrelationIdMiddleware:
    """Bind one request correlation ID for all work performed by an HTTP call."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = normalize_correlation_id(
            Headers(scope=scope).get("X-Request-ID")
        )
        token = set_correlation_id(correlation_id)

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            reset_correlation_id(token)
