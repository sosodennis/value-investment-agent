from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping

from sqlalchemy import select

from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.agents.intent.interface.serializers import (
    build_ticker_selection_interrupt_ui_payload,
)
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import ChatMessage
from src.shared.kernel.tools.logger import get_logger

logger = get_logger(__name__)


def _build_candidates(payload: Mapping[str, object]) -> list[TickerCandidate]:
    candidates_raw = payload.get("candidates")
    if not isinstance(candidates_raw, list):
        return []

    candidates: list[TickerCandidate] = []
    for entry in candidates_raw:
        if not isinstance(entry, Mapping):
            continue
        symbol = entry.get("symbol")
        name = entry.get("name")
        confidence = entry.get("confidence")
        if not isinstance(symbol, str) or not isinstance(name, str):
            continue
        confidence_val = confidence if isinstance(confidence, int | float) else 1.0
        candidates.append(
            TickerCandidate(
                symbol=symbol,
                name=name,
                exchange=entry.get("exchange")
                if isinstance(entry.get("exchange"), str)
                else None,
                type=entry.get("type") if isinstance(entry.get("type"), str) else None,
                confidence=float(confidence_val),
            )
        )
    return candidates


def _normalize_metadata(metadata: dict) -> tuple[dict, bool]:
    msg_type = metadata.get("type")
    if msg_type == "ticker_selection":
        payload = metadata.get("data")
        if not isinstance(payload, Mapping):
            logger.warning("ticker_selection payload missing or invalid; skipping")
            return metadata, False
        candidates = _build_candidates(payload)
        if not candidates:
            logger.warning("ticker_selection payload has no valid candidates; skipping")
            return metadata, False
        reason_raw = payload.get("reason")
        reason = (
            reason_raw
            if isinstance(reason_raw, str)
            else "Multiple tickers found or ambiguity detected."
        )
        metadata["type"] = "interrupt.request"
        metadata["data"] = build_ticker_selection_interrupt_ui_payload(
            candidates=candidates,
            reason=reason,
        )
        return metadata, True

    if msg_type == "technical_analysis":
        metadata["type"] = "text"
        metadata.pop("data", None)
        return metadata, True

    return metadata, False


async def migrate(*, apply_changes: bool) -> int:
    updated = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ChatMessage))
        rows = result.scalars().all()
        for row in rows:
            metadata = row.metadata_ or {}
            if not isinstance(metadata, dict):
                continue
            normalized, changed = _normalize_metadata(dict(metadata))
            if not changed:
                continue
            row.metadata_ = normalized
            updated += 1
        if apply_changes and updated:
            await session.commit()
        else:
            await session.rollback()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy message types to contract-compliant values."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates to the database (default is dry-run).",
    )
    args = parser.parse_args()

    updated = asyncio.run(migrate(apply_changes=args.apply))
    if args.apply:
        logger.info("message_type_migration_applied updated=%s", updated)
    else:
        logger.info("message_type_migration_dry_run updated=%s", updated)


if __name__ == "__main__":
    main()
