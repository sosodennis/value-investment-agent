"""Prepare immutable SEC annual statements with deployment mapping/release keys."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.exc import SQLAlchemyError

from .annual_discovery_service import AnnualDiscovery
from .automatic_data_release import (
    AutomaticDataReleaseService,
    AutomaticStatementReleasePolicyV1,
    automatic_release_suite_digest,
)
from .automatic_mapping import automatic_mapping_policy_digest
from .automatic_source_mapping import AutomaticSourceMappingAuthority
from .data_releases import DataReleaseError, DataReleaseTrustRootsV1
from .dqc_rulesets import DQC_V18_PROFILE_ID
from .operations import ServiceError
from .process_output import write_stdout
from .public_acquisition import PostgresPublicCaptureLock
from .serialization import canonical_bytes
from .snapshots import SnapshotError
from .statement_preparation import (
    AnnualStatementPreparationRequestV1,
    prepare_annual_statements,
)
from .statement_profiles import annual_statement_profile, statement_executable_digest


def _key(path: Path) -> Ed25519PrivateKey:
    value = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(value, Ed25519PrivateKey):
        raise ValueError("annual statements require an Ed25519 deployment key")
    return value


async def _run(args: argparse.Namespace) -> object:
    package_root = Path(__file__).resolve().parents[2]
    for root in (package_root, package_root.parent / "finance-agent-core"):
        if (root / "src/shared/internal_services").is_dir() and str(
            root
        ) not in sys.path:
            sys.path.insert(0, str(root))
    from .app import app

    async with app.router.lifespan_context(app):
        application, acquisition, metadata = (
            app.state.application,
            app.state.sec_acquisition,
            app.state.metadata_store,
        )
        if (
            not application.ready
            or acquisition is None
            or metadata is None
            or application.statement_originals is None
        ):
            raise SnapshotError(
                "STATEMENT_PREPARATION_UNAVAILABLE",
                "annual statements require SEC runtime, service persistence and deployment trust",
            )
        if args.print_runtime_pins:
            profiles = {}
            for profile_id in ("sec-efm-us-dqc-v31.0.3", DQC_V18_PROFILE_ID):
                try:
                    profiles[profile_id] = acquisition.original_validation_runtime(
                        declared_source_revision=args.source_revision,
                        validation_profile_id=profile_id,
                    )
                except ServiceError as error:
                    profiles[profile_id] = {"issue_code": error.code}
            return {
                "statement_profile": annual_statement_profile(
                    executable_digest=statement_executable_digest()
                ),
                "mapping_policy_digest": automatic_mapping_policy_digest(),
                "verification_suite_digest": automatic_release_suite_digest(),
                "validation_runtimes": profiles,
            }
        trust_path = os.getenv("FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE")
        if not trust_path:
            raise ValueError("FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE is required")
        roots = DataReleaseTrustRootsV1.from_file(Path(trust_path))
        acquisition.automatic_mapping_authority = AutomaticSourceMappingAuthority(
            artifacts=application.artifact_store,
            content=application.content_store,
            metadata=metadata,
            trust_roots=roots,
            private_key=_key(args.mapping_private_key),
            source_revision=args.source_revision,
            taxonomy_cache_dir=acquisition.settings.taxonomy_cache_dir,
            taxonomy_cache_sha256=acquisition.settings.taxonomy_cache_sha256,
        )
        policy = AutomaticStatementReleasePolicyV1.model_validate_json(
            args.release_policy.read_bytes()
        )
        release = AutomaticDataReleaseService(
            snapshots=application.snapshot_repository,
            facts=application.fact_repository,
            mappings=metadata,
            artifacts=application.artifact_store,
            trust_roots=roots,
            policy=policy,
            private_key=_key(args.release_private_key),
            source_revision=args.source_revision,
            statement_originals=application.statement_originals,
            statement_content=application.content_store,
        )
        request = AnnualStatementPreparationRequestV1(
            cik=args.cik,
            cutoff_at=args.cutoff_at,
            source_revision=args.source_revision,
            original_count=args.original_count,
            mapping_evaluator_id=args.mapping_evaluator_id,
            mapping_version=args.mapping_version,
            ticker=args.ticker,
            share_class=args.share_class,
        )
        discovery = AnnualDiscovery(
            provider=acquisition.adapter,
            artifacts=application.artifact_store,
            content=application.content_store,
            capture_lock=PostgresPublicCaptureLock(metadata),
        )
        return prepare_annual_statements(
            request,
            application=application,
            acquisition=acquisition,
            discovery=discovery,
            automatic_release=release,
            actor_id=args.actor,
            organization_id=args.organization,
            deadline_at=datetime.now(UTC) + timedelta(seconds=args.timeout_seconds),
            activate=args.activate,
            expected_revision=args.expected_revision,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-revision",
        required=True,
        help="Exact installed 40-character source revision",
    )
    parser.add_argument(
        "--print-runtime-pins",
        action="store_true",
        help="Read installed statement, mapping, validation and release suite pins",
    )
    parser.add_argument("--cik")
    parser.add_argument("--cutoff-at", help="Explicit ISO 8601 cutoff with timezone")
    parser.add_argument(
        "--original-count",
        type=int,
        default=5,
        help="Original annuals to freeze; production coverage target is five",
    )
    parser.add_argument("--ticker")
    parser.add_argument("--share-class")
    parser.add_argument("--mapping-evaluator-id")
    parser.add_argument("--mapping-version")
    parser.add_argument("--mapping-private-key", type=Path)
    parser.add_argument(
        "--release-policy",
        type=Path,
        help="AutomaticStatementReleasePolicyV1 deployment JSON",
    )
    parser.add_argument("--release-private-key", type=Path)
    parser.add_argument("--actor")
    parser.add_argument("--organization")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Activate the verified candidate through the existing compare-and-swap pointer",
    )
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args(argv)
    if not args.print_runtime_pins:
        required = (
            "cik",
            "cutoff_at",
            "mapping_evaluator_id",
            "mapping_version",
            "mapping_private_key",
            "release_policy",
            "release_private_key",
            "actor",
            "organization",
        )
        missing = tuple(
            name.replace("_", "-") for name in required if not getattr(args, name)
        )
        if missing:
            parser.error(
                "required for preparation: "
                + ", ".join("--" + name for name in missing)
            )
        if args.expected_revision is not None and not args.activate:
            parser.error("--expected-revision requires --activate")
    if not 1 <= args.timeout_seconds <= 14400:
        parser.error("--timeout-seconds must be between 1 and 14400")
    try:
        value = asyncio.run(_run(args))
    except (
        OSError,
        ValueError,
        SQLAlchemyError,
        DataReleaseError,
        SnapshotError,
        ServiceError,
    ) as error:
        code = getattr(error, "code", "STATEMENT_PREPARATION_FAILED")
        print(f"{code}: {error}", file=sys.stderr)
        return 2
    write_stdout(canonical_bytes(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
