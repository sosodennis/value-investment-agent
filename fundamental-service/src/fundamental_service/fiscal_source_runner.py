"""Discover, validate, or reread SEC fiscal originals using service persistence."""

from __future__ import annotations

import argparse
import os
import stat
import asyncio
import re
import sys
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from .arelle_parser import ArelleParserError
from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_candidate_contracts import (
    FiscalPrepareCandidateCommandV2,
    FiscalStatementCandidateV3,
)
from .fiscal_preparation_runtime import configured_fiscal_candidate_runtime
from .fiscal_discovery import FiscalDiscoveryEvidenceV1, FiscalDiscoveryRequestV1
from .fiscal_focus_witness import SignedFiscalDiagnosticFocusWitnessV1
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
    evidence: (
        FiscalDiscoveryEvidenceV1
        | FiscalOriginalValidationEvidenceV1
        | SignedFiscalDiagnosticFocusWitnessV1
        | FiscalStatementCandidateV3
    ) = Field(discriminator="protocol")
    publication: ArtifactPublicationV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


def _command_bytes(path: Path, deadline_at: datetime) -> bytes:
    fiscal_validation_budget(deadline_at)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise SnapshotError(
                "FISCAL_CANDIDATE_INPUT_INVALID",
                "candidate input must be a bounded regular file",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read(1024 * 1024 + 1)
        fiscal_validation_budget(deadline_at)
        if len(raw) > 1024 * 1024:
            raise SnapshotError(
                "FISCAL_CANDIDATE_INPUT_INVALID",
                "candidate input exceeds its byte limit",
            )
        return raw
    finally:
        os.close(descriptor)


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

    lifecycle = (
        app.state.read_only_operator_lifespan
        if args.command in {"read-candidate", "replay-candidate"}
        else app.router.lifespan_context
    )
    async with lifecycle(app):
        acquisition = app.state.fiscal_sec_acquisition
        if acquisition is None or not app.state.application.ready:
            raise SnapshotError(
                "FISCAL_VALIDATION_UNCONFIGURED",
                "fiscal validation requires SEC runtime and service persistence",
            )
        with metadata_operation_budget(
            partial(fiscal_validation_budget, deadline_at), sec_deadline_exceeded
        ):
            if args.command in {
                "prepare-candidate",
                "read-candidate",
                "replay-candidate",
            }:
                metadata = app.state.metadata_store
                if metadata is None:
                    raise SnapshotError(
                        "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                        "candidate requires PostgreSQL history",
                    )
                builder = configured_fiscal_candidate_runtime(
                    acquisition,
                    metadata,
                    declared_source_revision=args.source_revision,
                    write=args.command == "prepare-candidate",
                )
                if args.command == "prepare-candidate":
                    result = builder.prepare(
                        FiscalPrepareCandidateCommandV2.model_validate_json(
                            _command_bytes(args.command_file, deadline_at)
                        ),
                        deadline_at=deadline_at,
                    )
                else:
                    reader = (
                        builder.replay_candidate
                        if args.command == "replay-candidate"
                        else builder.verify_candidate
                    )
                    result = reader(
                        ArtifactRefV1.model_validate_json(
                            _command_bytes(args.candidate_ref_file, deadline_at)
                        ),
                        deadline_at=deadline_at,
                    )
                return _FiscalCommandOutput(
                    evidence=result.candidate, publication=result.candidate_publication
                )
            if args.command in {"focus-witness", "read-focus-witness"}:
                owner = acquisition.fiscal_focus_witness(
                    declared_source_revision=args.source_revision
                )
                if args.command == "read-focus-witness":
                    return _FiscalCommandOutput(
                        evidence=owner.read(args.artifact_id, deadline_at=deadline_at)
                    )
                store = acquisition.capture_store
                if store is None:
                    raise SnapshotError(
                        "SEC_CAPTURE_STORE_UNAVAILABLE", "evidence unavailable"
                    )
                record = store.get(args.source_artifact_id)
                result = owner.execute(
                    ArtifactRefV1(
                        role="fiscal-original-validation",
                        artifact_id=record.artifact_id,
                        media_type=record.media_type,
                        content_hash=record.content_hash,
                    ),
                    deadline_at=deadline_at,
                )
                return _FiscalCommandOutput(
                    evidence=result.witness, publication=result.publication
                )
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
    witness = commands.add_parser("focus-witness")
    witness.add_argument("--source-artifact-id", required=True)
    witness_read = commands.add_parser("read-focus-witness")
    witness_read.add_argument("--artifact-id", required=True)
    candidate = commands.add_parser("prepare-candidate")
    candidate.add_argument("--command-file", type=Path, required=True)
    candidate_read = commands.add_parser("read-candidate")
    candidate_read.add_argument("--candidate-ref-file", type=Path, required=True)
    candidate_replay = commands.add_parser("replay-candidate")
    candidate_replay.add_argument("--candidate-ref-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--source-revision requires a lowercase Git revision")
    if not 1 <= args.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 1 and 900")
    deadline_at = datetime.now(UTC) + timedelta(seconds=args.timeout_seconds)
    try:
        with metadata_operation_budget(
            partial(fiscal_validation_budget, deadline_at), sec_deadline_exceeded
        ):
            result = asyncio.run(_run(args, deadline_at=deadline_at))
            write_stdout(
                (
                    canonical_bytes(result)
                    if isinstance(result.evidence, FiscalStatementCandidateV3)
                    else canonical_bytes(result.model_dump(mode="json"))
                )
                + b"\n",
                remaining_budget=partial(fiscal_validation_budget, deadline_at),
            )
    except (SnapshotError, SecSourceError, ServiceError) as error:
        print(
            canonical_bytes(
                {"error_code": error.code, "retryable": error.retryable}
            ).decode(),
            file=sys.stderr,
        )
        return 2
    except ArelleParserError as error:
        print(
            canonical_bytes(
                {
                    "error_code": error.code,
                    "retryable": error.code
                    in {
                        "REQUEST_DEADLINE_EXCEEDED",
                        "PARSER_CONCURRENCY_EXHAUSTED",
                        "PARSER_RESOURCE_EXHAUSTED",
                    },
                }
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
