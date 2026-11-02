from __future__ import annotations

from src.client_debug.application.service import ClientDebugService
from src.client_debug.config import ClientDebugSettings
from src.client_debug.infrastructure.runtime_buffer import ClientDebugBuffer

_client_debug_service: ClientDebugService | None = None
_client_debug_buffer: ClientDebugBuffer | None = None


def get_client_debug_service() -> ClientDebugService:
    global _client_debug_service, _client_debug_buffer
    if _client_debug_service is None:
        settings = ClientDebugSettings.from_environment()
        _client_debug_buffer = ClientDebugBuffer(settings=settings)
        _client_debug_service = ClientDebugService(
            buffer=_client_debug_buffer,
            settings=settings,
        )
    return _client_debug_service


def reset_client_debug_wiring() -> None:
    global _client_debug_service, _client_debug_buffer
    _client_debug_service = None
    _client_debug_buffer = None
