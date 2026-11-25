"""Discover, validate, or reread SEC fiscal originals using service persistence."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_discovery import FiscalDiscoveryEvidenceV1, FiscalDiscoveryRequestV1
from .fiscal_source_validation import fiscal_validation_budget
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalOriginalValidationRequestV1,
)
from .metadata import metadata_operation_budget
from .operations import ServiceError
from .process_output import write_stdout
from .replay import ArtifactPublicationV1
from .sec_source import SecSourceError, sec_deadline_exceeded
from .serialization import canonical_bytes
from .snapshots import SnapshotError


class _FiscalCommandOutput(StrictModel):
    evidence: FiscalDiscoveryEvidenceV1 | FiscalOriginalValidationEvidenceV1 = Field(
        discriminator="protocol"
    )
    publication: ArtifactPublicationV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


async def _run(
    args: argparse.Namespace, *, deadline_at: datetime
) -> _FiscalCommandOutput:
    package_root = Path(__file__).resolve().parents[2]
    for root in (package_root, package_root.parent / "finance-agent-core"):
        if (root / "src/shared/internal_services").is_dir() and str(
            root
        ) not in sys.path:
            sys.path.insert(0, str(root))
    from .app import app

    async with app.router.lifespan_context(app):
        acquisition = app.state.sec_acquisition
        if acquisition is None or not app.state.application.ready:
            raise SnapshotError(
                "FISCAL_VALIDATION_UNCONFIGURED",
                "fiscal validation requires SEC runtime and service persistence",
            )
        with metadata_operation_budget(
            partial(fiscal_validation_budget, deadline_at), sec_deadline_exceeded
        ):
            closure = acquisition.fiscal_source_closure(
                declared_source_revision=args.source_revision
            )
            if args.command == "discover":
                discovery = acquisition.fiscal_discovery()
                request = FiscalDiscoveryRequestV1(
                    cik=args.cik.zfill(10),
                    valuation_timestamp=datetime.fromisoformat(
                        args.valuation_timestamp
                    ),
                    declared_source_revision=args.source_revision,
                    supported_filing_years=acquisition.settings.supported_filing_years,
                    lookback_days=args.lookback_days,
                )
                evidence, publication = discovery.execute(
                    request, deadline_at=deadline_at
                )
                return _FiscalCommandOutput(evidence=evidence, publication=publication)
            if args.command == "read":
                return _FiscalCommandOutput(
                    evidence=closure.read(args.artifact_id, deadline_at=deadline_at)
                )
            store = acquisition.capture_store
            assert store is not None
            record = store.get(args.discovery_artifact_id)
            evidence, publication = closure.execute(
                FiscalOriginalValidationRequestV1(
                    discovery_ref=ArtifactRefV1(
                        role="fiscal-discovery",
                        artifact_id=record.artifact_id,
                        media_type=record.media_type,
                        content_hash=record.content_hash,
                    ),
                    accession_number=args.accession,
                ),
                deadline_at=deadline_at,
            )
            return _FiscalCommandOutput(evidence=evidence, publication=publication)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    commands = parser.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser("discover")
    discovery.add_argument("--cik", required=True)
    discovery.add_argument("--valuation-timestamp", required=True)
    discovery.add_argument("--lookback-days", type=int, default=3650)
    validate = commands.add_parser("validate")
    validate.add_argument("--discovery-artifact-id", required=True)
    validate.add_argument("--accession", required=True)
    read = commands.add_parser("read")
    read.add_argument("--artifact-id", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--source-revision requires a lowercase Git revision")
    if not 1 <= args.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 1 and 900")
    deadline_at = datetime.now(UTC) + timedelta(seconds=args.timeout_seconds)
    try:
        result = asyncio.run(_run(args, deadline_at=deadline_at))
        write_stdout(canonical_bytes(result.model_dump(mode="json")) + b"\n")
    except (SnapshotError, SecSourceError, ServiceError) as error:
        print(
            canonical_bytes(
                {"error_code": error.code, "retryable": error.retryable}
            ).decode(),
            file=sys.stderr,
        )
        return 2
    except SQLAlchemyError:
        print('{"error_code":"FISCAL_VALIDATION_STORAGE_FAILED"}', file=sys.stderr)
        return 2
    except OSError:
        print('{"error_code":"FISCAL_VALIDATION_IO_FAILED"}', file=sys.stderr)
        return 2
    except (ValueError, TypeError):
        print('{"error_code":"FISCAL_VALIDATION_INPUT_INVALID"}', file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
