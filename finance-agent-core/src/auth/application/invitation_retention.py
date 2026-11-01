from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.auth.application.invitation_ports import InvitationRetentionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InvitationRetentionResult:
    expired: int
    purged: int


async def run_invitation_retention(
    repository: InvitationRetentionRepository,
    *,
    now: datetime | None = None,
    terminal_retention_days: int = 90,
    batch_limit: int = 100,
) -> InvitationRetentionResult:
    if terminal_retention_days < 1 or not 1 <= batch_limit <= 1_000:
        raise ValueError("invitation retention bounds are invalid")
    current_time = now or datetime.now(UTC)
    expired, purged = await repository.expire_and_purge(
        now=current_time,
        terminal_before=current_time - timedelta(days=terminal_retention_days),
        limit=batch_limit,
    )
    logger.info(
        "invitation retention batch completed",
        extra={"expired": expired, "purged": purged, "batch_limit": batch_limit},
    )
    return InvitationRetentionResult(expired=expired, purged=purged)
