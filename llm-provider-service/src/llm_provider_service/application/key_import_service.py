from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from uuid import uuid4

import httpx
from pydantic import SecretStr

from src.llm_provider_service.domain.errors import OpenRouterKeyTestError
from src.llm_provider_service.domain.key_imports import (
    ClaimedKeyImportItem,
    KeyImportInput,
    KeyImportSnapshot,
)
from src.llm_provider_service.infrastructure.embedded_runtime import (
    EmbeddedLiteLLMProvider,
)
from src.llm_provider_service.infrastructure.openrouter_key_test import (
    validate_openrouter_key,
)
from src.llm_provider_service.infrastructure.state import ProviderState

logger = logging.getLogger(__name__)

_MAX_RETRY_DELAY_SECONDS = 60.0
_POLL_INTERVAL_SECONDS = 0.5


def _concurrency() -> int:
    try:
        configured = int(os.getenv("LLM_PROVIDER_IMPORT_CONCURRENCY", "5"))
    except ValueError:
        configured = 5
    return min(max(configured, 1), 10)


def _safe_label(label: str, key: str) -> str:
    value = label.strip() or "OpenRouter key"
    if key in value:
        value = value.replace(key, "[redacted]")
    return value[:80]


class ProviderKeyImportService:
    def __init__(
        self,
        *,
        state: ProviderState,
        provider: EmbeddedLiteLLMProvider,
        concurrency: int | None = None,
        validate_key: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._state = state
        self._provider = provider
        self._concurrency = concurrency or _concurrency()
        self._validate_key = validate_key
        self._client: httpx.AsyncClient | None = None
        self._worker_id = str(uuid4())
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_import(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        items: Sequence[tuple[int, str, SecretStr]],
    ) -> KeyImportSnapshot:
        normalized = [
            KeyImportInput(
                source_line=line,
                label=_safe_label(label, secret.get_secret_value()),
                api_key=secret.get_secret_value(),
            )
            for line, label, secret in items
        ]
        return await self._state.create_key_import(
            user_id=user_id,
            idempotency_key=idempotency_key,
            items=normalized,
        )

    async def list_imports(self, *, user_id: str) -> list[KeyImportSnapshot]:
        return await self._state.list_key_imports(user_id=user_id)

    async def get_import(
        self, *, user_id: str, batch_id: str
    ) -> KeyImportSnapshot | None:
        return await self._state.get_key_import(user_id=user_id, batch_id=batch_id)

    async def retry_import(
        self, *, user_id: str, batch_id: str
    ) -> KeyImportSnapshot | None:
        return await self._state.retry_key_import(user_id=user_id, batch_id=batch_id)

    async def _run(self) -> None:
        next_cleanup_at = 0.0
        while True:
            try:
                now = time.monotonic()
                if now >= next_cleanup_at:
                    await self._state.cleanup_key_imports()
                    next_cleanup_at = now + 60.0
                await self._refresh_completed_batches()
                items = await self._state.claim_key_import_items(
                    worker_id=self._worker_id,
                    limit=self._concurrency,
                )
                if items:
                    await asyncio.gather(
                        *(self._process(item) for item in items),
                        return_exceptions=True,
                    )
                    await self._refresh_completed_batches()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Provider key import worker iteration failed (%s)",
                    type(exc).__name__,
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _refresh_completed_batches(self) -> None:
        claimed = await self._state.claim_key_import_router_refreshes(
            worker_id=self._worker_id
        )
        for batch_id in claimed:
            try:
                await self._provider.refresh_after_key_import()
                await self._state.mark_key_import_router_refreshed(
                    batch_id=batch_id,
                    worker_id=self._worker_id,
                )
            except asyncio.CancelledError:
                await self._state.release_key_import_router_refresh(
                    batch_id=batch_id,
                    worker_id=self._worker_id,
                )
                raise
            except Exception as exc:
                await self._state.release_key_import_router_refresh(
                    batch_id=batch_id,
                    worker_id=self._worker_id,
                )
                logger.warning(
                    "Provider key import router refresh failed (%s)",
                    type(exc).__name__,
                )

    async def _process(self, item: ClaimedKeyImportItem) -> None:
        try:
            async with self._state.fingerprint_lock(
                user_id=item.user_id,
                fingerprint=item.fingerprint,
            ):
                existing = await self._state.find_import_deployment(
                    user_id=item.user_id,
                    fingerprint=item.fingerprint,
                )
                if existing is not None:
                    await self._state.finish_import_duplicate(item=item)
                    return
                try:
                    await self._validate(item.api_key)
                except OpenRouterKeyTestError as exc:
                    code = exc.code
                    retryable = code not in {"invalid_key", "request_rejected"}
                    await self._state.finish_import_failure(
                        item=item,
                        error_code=code
                        if code
                        in {
                            "invalid_key",
                            "request_rejected",
                            "rate_limited",
                            "upstream_unavailable",
                        }
                        else "upstream_unavailable",
                        retryable=retryable,
                        delay_seconds=self._retry_delay(
                            item.attempts, exc.retry_after_seconds
                        ),
                    )
                    return
                model = await self._state.get_selected_model()
                await self._state.finish_import_success(item=item, model=model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Provider key import item deferred after worker error (%s)",
                type(exc).__name__,
            )

    async def _validate(self, key: str) -> None:
        if self._validate_key is not None:
            await self._validate_key(key)
            return
        if self._client is None:
            raise RuntimeError("provider key import worker is not started")
        await validate_openrouter_key(key, client=self._client)

    @staticmethod
    def _retry_delay(attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(retry_after, 0.0), _MAX_RETRY_DELAY_SECONDS)
        return min(2.0 ** max(attempt - 1, 0), 8.0)
