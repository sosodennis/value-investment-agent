from __future__ import annotations

import asyncio

from src.auth.application.invitation_retention import run_invitation_retention
from src.auth.application.rate_limit import rate_limit_settings
from src.auth.infrastructure.retention_repository import (
    SqlAlchemyInvitationRetentionRepository,
)
from src.infrastructure.database import engine


async def _main() -> None:
    try:
        result = await run_invitation_retention(
            SqlAlchemyInvitationRetentionRepository(),
            terminal_retention_days=rate_limit_settings.retention_days,
        )
        print(
            "Invitation retention expired "
            f"{result.expired} invitations and purged {result.purged} terminal rows"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
