from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.notifications.application.retention import run_notification_retention


class FakeRetentionRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, int]] = []

    async def purge_expired(
        self, *, created_before: datetime, expired_before: datetime, limit: int
    ) -> int:
        self.calls.append((created_before, expired_before, limit))
        return 2


@pytest.mark.asyncio
async def test_retention_is_bounded_and_reports_deleted_events() -> None:
    repository = FakeRetentionRepository()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    result = await run_notification_retention(repository, now=now, batch_limit=25)
    assert result.deleted_events == 2
    assert result.batch_limit == 25
    assert repository.calls == [
        (datetime(2025, 10, 3, tzinfo=UTC), datetime(2025, 12, 2, tzinfo=UTC), 25)
    ]
