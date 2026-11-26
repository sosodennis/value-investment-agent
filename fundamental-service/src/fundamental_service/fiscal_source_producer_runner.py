"""Execute one installed source preparation or accounting classifier order."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .fiscal_source_producer_runtime import configured_source_producer_runtime
from .process_output import write_stdout
from .serialization import canonical_bytes
from .snapshots import SnapshotError


async def _run(args: argparse.Namespace, deadline_at: datetime) -> object:
    package_root = Path(__file__).resolve().parents[2]
    core = package_root.parent / "finance-agent-core"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    from .app import app

    async with app.state.read_only_operator_lifespan(app):
        acquisition, metadata = (
            app.state.fiscal_sec_acquisition,
            app.state.metadata_store,
        )
        if acquisition is None or metadata is None:
            raise SnapshotError(
                "FISCAL_SOURCE_PRODUCER_UNCONFIGURED",
                "source producer requires SEC and PostgreSQL persistence",
            )
        runtime = configured_source_producer_runtime(
            acquisition, metadata, role=args.role
        )
        return runtime.run(args.protected_order_id, deadline_at=deadline_at)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("source_preparer", "classifier"))
    parser.add_argument("protected_order_id")
    parser.add_argument("--deadline-seconds", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.deadline_seconds <= 300:
        parser.error("deadline-seconds must be within (0, 300]")
    try:
        result = asyncio.run(
            _run(args, datetime.now(UTC) + timedelta(seconds=args.deadline_seconds))
        )
        write_stdout(canonical_bytes(result))
    except SnapshotError as error:
        write_stdout(
            canonical_bytes({"error": {"code": error.code, "message": str(error)}})
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
