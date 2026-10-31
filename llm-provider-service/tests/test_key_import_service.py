from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from src.llm_provider_service.application.key_import_service import (
    ProviderKeyImportService,
)
from src.llm_provider_service.domain.errors import OpenRouterKeyTestError
from src.llm_provider_service.domain.key_imports import ClaimedKeyImportItem


class _State:
    def __init__(self) -> None:
        self.failures: list[dict[str, object]] = []
        self.successes: list[dict[str, object]] = []

    @asynccontextmanager
    async def fingerprint_lock(
        self, *, user_id: str, fingerprint: str
    ) -> AsyncIterator[None]:
        _ = (user_id, fingerprint)
        yield

    async def find_import_deployment(self, *, user_id: str, fingerprint: str) -> None:
        _ = (user_id, fingerprint)
        return None

    async def get_selected_model(self) -> str:
        return "openrouter/free"

    async def finish_import_failure(self, **values: object) -> None:
        self.failures.append(values)

    async def finish_import_success(self, **values: object) -> None:
        self.successes.append(values)


def _item(*, attempts: int = 1) -> ClaimedKeyImportItem:
    return ClaimedKeyImportItem(
        id="item-id",
        batch_id="batch-id",
        user_id="owner-id",
        source_line=1,
        label="staging key",
        fingerprint="safe-fingerprint",
        suffix="0001",
        api_key="synthetic-key-material-not-for-logs",
        attempts=attempts,
        worker_id="worker-id",
    )


@pytest.mark.asyncio
async def test_invalid_key_is_terminal_and_transient_retry_after_is_bounded() -> None:
    state = _State()

    async def invalid_validator(_key: str) -> None:
        raise OpenRouterKeyTestError("invalid_key")

    service = ProviderKeyImportService(
        state=state,
        provider=SimpleNamespace(),
        validate_key=invalid_validator,
    )
    await service._process(_item())
    assert state.failures == [
        {
            "item": _item(),
            "error_code": "invalid_key",
            "retryable": False,
            "delay_seconds": 1,
        }
    ]

    async def rate_limited_validator(_key: str) -> None:
        raise OpenRouterKeyTestError("rate_limited", retry_after_seconds=3600)

    retry_service = ProviderKeyImportService(
        state=state,
        provider=SimpleNamespace(),
        validate_key=rate_limited_validator,
    )
    await retry_service._process(_item(attempts=2))
    assert state.failures[-1]["error_code"] == "rate_limited"
    assert state.failures[-1]["retryable"] is True
    assert state.failures[-1]["delay_seconds"] == 60


def test_retry_delay_caps_retry_after_and_uses_bounded_backoff() -> None:
    assert ProviderKeyImportService._retry_delay(1, 90) == 60
    assert ProviderKeyImportService._retry_delay(4, None) == 8
    assert ProviderKeyImportService._retry_delay(0, None) == 1
