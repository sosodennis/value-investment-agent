from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.technical.subdomains.decision_observability import (  # noqa: E402
    build_default_technical_outcome_labeling_worker_service,
)
from src.shared.kernel.tools.logger import get_logger, log_event  # noqa: E402

logger = get_logger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one delayed-labeling pass for technical decision observability."
        ),
    )
    parser.add_argument(
        "--as-of-time",
        type=_parse_as_of_time,
        default=None,
        help="Optional ISO8601 timestamp to use as the maturity boundary.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum unresolved prediction events to scan in one pass.",
    )
    parser.add_argument(
        "--labeling-method-version",
        type=str,
        default="technical_outcome_labeling.v1",
        help="Outcome labeling method version to write into raw outcome rows.",
    )
    return parser.parse_args(argv)


async def _run_once(args: argparse.Namespace) -> dict[str, object]:
    worker = build_default_technical_outcome_labeling_worker_service()
    result = await worker.run_once(
        as_of_time=args.as_of_time,
        limit=max(int(args.limit), 1),
        labeling_method_version=args.labeling_method_version,
    )
    return {
        "status": "done",
        "scanned_event_count": result.scanned_event_count,
        "matured_event_count": result.matured_event_count,
        "inserted_outcome_count": result.inserted_outcome_count,
        "skipped_existing_count": result.skipped_existing_count,
        "failed_event_ids": list(result.failed_event_ids),
        "provider_failures": list(result.provider_failures),
    }


def _parse_as_of_time(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = asyncio.run(_run_once(args))
    log_event(
        logger,
        event="technical_outcome_labeling_script_completed",
        message="technical outcome labeling script completed",
        fields=payload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
