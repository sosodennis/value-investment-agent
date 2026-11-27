"""Execute one protected independent fiscal display review order."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .content_publication import configured_content_publication_access
from .fiscal_display_runtime import (
    FiscalDisplayRuntime,
    _budget,
    load_display_installation,
    require_candidate_configuration,
)
from .fiscal_preparation_runtime import configured_fiscal_candidate_runtime
from .metadata import PostgresArtifactStore, PostgresContentStore
from .process_output import write_stdout
from .serialization import canonical_bytes
from .snapshots import SnapshotError


async def _run(order_id: str, deadline_at: datetime) -> bytes:
    installation = load_display_installation()
    require_candidate_configuration(installation)
    package_root = Path(__file__).resolve().parents[2]
    for root in (package_root, package_root.parent / "finance-agent-core"):
        if (root / "src/shared/internal_services").is_dir() and str(
            root
        ) not in sys.path:
            sys.path.insert(0, str(root))
    from .app import app

    async with app.state.read_only_operator_lifespan(app):
        acquisition, metadata = (
            app.state.fiscal_sec_acquisition,
            app.state.metadata_store,
        )
        if acquisition is None or metadata is None or acquisition.capture_store is None:
            raise SnapshotError(
                "FISCAL_DISPLAY_UNCONFIGURED",
                "display requires configured candidate and PostgreSQL owners",
            )
        candidates = configured_fiscal_candidate_runtime(
            acquisition,
            metadata,
            declared_source_revision=installation.declared_source_revision,
            write=False,
        )
        runtime = FiscalDisplayRuntime(
            installation=installation,
            candidates=candidates,
            artifacts=PostgresArtifactStore(
                metadata,
                PostgresContentStore(
                    Path(os.environ["FUNDAMENTAL_SERVICE_DATA_ROOT"]) / "content",
                    metadata,
                    publication_access=configured_content_publication_access(),
                ),
            ),
            metadata=metadata,
            installation_file=Path("/etc/fundamental/fiscal-display/installation.json"),
        )
        result = runtime.apply(order_id, deadline_at=deadline_at)
        return canonical_bytes(
            {
                "decision_ref": result.reference,
                "decision": result.decision,
                "publication": result.publication,
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protected_order_id")
    parser.add_argument("--deadline-seconds", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.deadline_seconds <= 300:
        parser.error("deadline-seconds must be within (0, 300]")
    deadline_at = datetime.now(UTC) + timedelta(seconds=args.deadline_seconds)
    try:
        payload = asyncio.run(_run(args.protected_order_id, deadline_at))
        if datetime.now(UTC) >= deadline_at:
            raise SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED",
                "display output deadline expired",
                retryable=True,
            )
        write_stdout(payload, remaining_budget=lambda: _budget(deadline_at))
    except SnapshotError as error:
        write_stdout(
            canonical_bytes({"error": {"code": error.code, "message": str(error)}})
        )
        return 1
    except (OSError, ValueError, KeyError, SQLAlchemyError):
        write_stdout(
            canonical_bytes(
                {
                    "error": {
                        "code": "FISCAL_DISPLAY_UNAVAILABLE",
                        "message": "display configuration or storage is unavailable",
                    }
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
