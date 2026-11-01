from __future__ import annotations

import asyncio

from src.auth.application.invitation_retention import run_invitation_retention
from src.auth.application.rate_limit import rate_limit_settings
from src.auth.infrastructure.retention_repository import (
    SqlAlchemyInvitationRetentionRepository,
)
from src.infrastructure.database import engine
from src.notifications.application.retention import run_notification_retention
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository


async def _main() -> None:
    try:
        invitation_result = await run_invitation_retention(
            SqlAlchemyInvitationRetentionRepository(),
            terminal_retention_days=rate_limit_settings.retention_days,
        )
        notification_result = await run_notification_retention(
            SqlAlchemyNotificationRepository(),
            retention_days=rate_limit_settings.retention_days,
            expired_retention_days=rate_limit_settings.expired_notification_retention_days,
        )
        print(
            "Collaboration retention completed: "
            f"expired_invites={invitation_result.expired}, "
            f"purged_invites={invitation_result.purged}, "
            f"purged_notification_events={notification_result.deleted_events}"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
