#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os

from src.llm_provider_service.infrastructure.state import ProviderState


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-encrypt organization LLM credentials in one transaction."
    )
    parser.add_argument("--confirm", action="store_true", help="confirm the rotation")
    return parser


async def _run(*, confirm: bool) -> None:
    if not confirm:
        raise SystemExit("refusing to rotate without --confirm")
    old_key = os.getenv("LLM_OLD_ENCRYPTION_KEY", "").strip()
    new_key = os.getenv("LLM_NEW_ENCRYPTION_KEY", "").strip()
    if not old_key or not new_key:
        raise SystemExit(
            "LLM_OLD_ENCRYPTION_KEY and LLM_NEW_ENCRYPTION_KEY are required"
        )
    state = ProviderState(encryption_key=old_key)
    try:
        await state.initialize()
        count = await state.rotate_encryption_key(old_key=old_key, new_key=new_key)
    finally:
        await state.close()
    print(f"rotated {count} LLM provider ciphertexts")


if __name__ == "__main__":
    args = _parser().parse_args()
    asyncio.run(_run(confirm=args.confirm))
