from __future__ import annotations

import asyncio

from src.auth.application.rate_limit import rate_limit_settings
from src.infrastructure.database import engine
from src.notifications.application.retention import run_notification_retention
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository


async def _main() -> None:
    try:
        result = await run_notification_retention(
            SqlAlchemyNotificationRepository(),
            retention_days=rate_limit_settings.retention_days,
            expired_retention_days=rate_limit_settings.expired_notification_retention_days,
        )
        print(f"Notification retention deleted {result.deleted_events} events")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
