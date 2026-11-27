"""Apply one installed fiscal registry order under the registry workload."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from .fiscal_registry_runtime import configured_fiscal_registry_runtime
from .process_output import write_stdout
from .serialization import canonical_bytes
from .snapshots import SnapshotError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protected_order_id")
    parser.add_argument("--deadline-seconds", type=float, default=30)
    args = parser.parse_args()
    if not 0 < args.deadline_seconds <= 300:
        parser.error("deadline-seconds must be within (0, 300]")
    deadline_at = datetime.now(UTC) + timedelta(seconds=args.deadline_seconds)
    try:
        with configured_fiscal_registry_runtime() as registry:
            result = registry.apply(args.protected_order_id, deadline_at=deadline_at)
        write_stdout(canonical_bytes(result))
    except SnapshotError as error:
        write_stdout(
            canonical_bytes({"error": {"code": error.code, "message": str(error)}})
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
