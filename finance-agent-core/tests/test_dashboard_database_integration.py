from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from src.dashboard.contracts import DashboardStatus
from src.dashboard.infrastructure import HttpReadinessProvider

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("POSTGRES_INTEGRATION_TESTS", "0").strip() != "1",
        reason="Set POSTGRES_INTEGRATION_TESTS=1 to probe the configured PostgreSQL database.",
    ),
]


@pytest.mark.asyncio
async def test_database_readiness_probes_postgresql() -> None:
    result = await HttpReadinessProvider._database_capability(
        datetime.now(timezone.utc)
    )
    assert result.id == "database"
    assert result.status == DashboardStatus.OPERATIONAL
    assert result.source == "postgresql"
