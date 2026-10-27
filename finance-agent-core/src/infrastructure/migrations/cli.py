from __future__ import annotations

import asyncio

from src.infrastructure.database import engine, init_db
from src.infrastructure.migrations import run_history_migration


async def _main() -> None:
    try:
        await init_db()
        result = await run_history_migration()
        if not result.completed:
            raise RuntimeError("database migration did not complete")
        print(f"Database migrations complete: {result.batches_processed} batches")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
