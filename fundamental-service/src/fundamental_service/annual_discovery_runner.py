"""Discover or retrieve a frozen SEC annual catalog using service persistence."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .annual_discovery import AnnualDiscoveryParametersV1, AnnualDiscoveryRequestV1
from .annual_discovery_service import AnnualDiscovery
from .public_acquisition import PostgresPublicCaptureLock
from .serialization import canonical_bytes
from .snapshots import SnapshotError


async def _run_command(args: argparse.Namespace) -> object:
    package_root = Path(__file__).resolve().parents[2]
    for root in (package_root, package_root.parent / "finance-agent-core"):
        if (root / "src/shared/internal_services").is_dir() and str(
            root
        ) not in sys.path:
            sys.path.insert(0, str(root))
    from .app import app

    async with app.router.lifespan_context(app):
        application = app.state.application
        acquisition = app.state.sec_acquisition
        metadata = app.state.metadata_store
        if (
            not application.ready
            or acquisition is None
            or metadata is None
            or application.content_store is None
        ):
            raise SnapshotError(
                "ANNUAL_DISCOVERY_UNCONFIGURED",
                "annual discovery requires SEC runtime and service persistence",
            )
        discovery = AnnualDiscovery(
            provider=acquisition.adapter,
            artifacts=application.artifact_store,
            content=application.content_store,
            capture_lock=PostgresPublicCaptureLock(metadata),
        )
        if args.artifact_id:
            evidence = discovery.read(args.artifact_id)
            return {
                "artifact": application.artifact_store.get(args.artifact_id),
                "input_digest": evidence.request.digest,
                "output_digest": evidence.digest,
                "evidence": evidence,
                "wrote": False,
            }
        request = AnnualDiscoveryRequestV1.model_validate(
            {
                **args.request.model_dump(),
                "supported_filing_years": acquisition.settings.supported_filing_years,
                "supported_filing_forms": acquisition.settings.supported_filing_forms,
            }
        )
        evidence, publication = discovery.execute(
            request,
            deadline_at=datetime.now(UTC) + timedelta(seconds=args.timeout_seconds),
        )
        return {
            "artifact": publication.artifact,
            "input_digest": request.digest,
            "output_digest": evidence.digest,
            "evidence": evidence,
            "wrote": publication.wrote,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik")
    parser.add_argument("--valuation-timestamp")
    parser.add_argument("--source-revision")
    parser.add_argument("--original-count", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=3650)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--artifact-id")
    args = parser.parse_args(argv)
    if args.artifact_id:
        if args.cik or args.valuation_timestamp or args.source_revision:
            parser.error("retrieval cannot also request a new annual selection")
    elif not args.cik or not args.valuation_timestamp or not args.source_revision:
        parser.error("discovery requires CIK, valuation timestamp and source revision")
    if not 1 <= args.timeout_seconds <= 900:
        parser.error("timeout must be between 1 and 900 seconds")
    try:
        # Validate caller-controlled fields before opening service storage.
        args.request = (
            None
            if args.artifact_id
            else AnnualDiscoveryParametersV1(
                cik=args.cik.zfill(10),
                valuation_timestamp=datetime.fromisoformat(args.valuation_timestamp),
                declared_source_revision=args.source_revision,
                original_count=args.original_count,
                lookback_days=args.lookback_days,
            )
        )
        result = asyncio.run(_run_command(args))
    except SnapshotError as error:
        print(
            canonical_bytes(
                {"error_code": error.code, "retryable": error.retryable}
            ).decode(),
            file=sys.stderr,
        )
        return 2
    except SQLAlchemyError:
        print('{"error_code":"ANNUAL_DISCOVERY_STORAGE_FAILED"}', file=sys.stderr)
        return 2
    except OSError:
        print('{"error_code":"ANNUAL_DISCOVERY_IO_FAILED"}', file=sys.stderr)
        return 2
    except (ValueError, TypeError):
        print('{"error_code":"ANNUAL_DISCOVERY_INPUT_INVALID"}', file=sys.stderr)
        return 2
    print(canonical_bytes(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
