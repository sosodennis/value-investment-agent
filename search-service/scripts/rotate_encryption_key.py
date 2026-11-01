#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os

from search_service.postgres_control_plane import PostgresSearchControlPlane


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-encrypt organization Search credentials in one transaction."
    )
    parser.add_argument("--confirm", action="store_true", help="confirm the rotation")
    return parser


async def _run(*, confirm: bool) -> None:
    if not confirm:
        raise SystemExit("refusing to rotate without --confirm")
    dsn = os.getenv("SEARCH_CONTROL_DATABASE_URL", "").strip()
    old_key = os.getenv("SEARCH_OLD_ENCRYPTION_KEY", "").strip()
    new_key = os.getenv("SEARCH_NEW_ENCRYPTION_KEY", "").strip()
    if not dsn or not old_key or not new_key:
        raise SystemExit(
            "SEARCH_CONTROL_DATABASE_URL, SEARCH_OLD_ENCRYPTION_KEY, and "
            "SEARCH_NEW_ENCRYPTION_KEY are required"
        )
    store = PostgresSearchControlPlane(dsn, old_key)
    try:
        count = await store.rotate_encryption_key(old_key=old_key, new_key=new_key)
    finally:
        await store.aclose()
    print(f"rotated {count} Search provider ciphertexts")


if __name__ == "__main__":
    args = _parser().parse_args()
    asyncio.run(_run(confirm=args.confirm))
