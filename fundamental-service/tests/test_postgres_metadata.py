from __future__ import annotations

import asyncio
import base64
import json
import multiprocessing
import os
import time
from contextvars import ContextVar
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncTransaction

from fundamental_service.app import create_app
from fundamental_service.contracts import (
    CandidateRejectionV1,
    CanonicalFactV1,
    FiscalPeriodSelectorV1,
    IdentityV1,
    PeriodType,
    QualityStatus,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecIngestionResponseV1,
    SecMappingReferenceV1,
    SourceProvenanceV1,
    SourceRecordV1,
    SourceRole,
    SourceSnapshotV1,
    XbrlContextV1,
)
from fundamental_service.data_releases import (
    REQUIRED_DATA_RELEASE_GATES,
    DataReleaseActivationCommandV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    DataReleaseVerifierV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1, canonical_fact_digest
from fundamental_service.metadata import (
    SCHEMA_VERSION,
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
    metadata_operation_budget,
)
from fundamental_service.operations import OperationsConfig
from fundamental_service.policies import PolicyRecordV1, initial_model_specs
from fundamental_service.replay import ArtifactPublicationDeadlineExceeded
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    SecSourceError,
    sec_deadline_exceeded,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_acquisition import SecAcquisitionUseCase
from fundamental_service.testsupport import (
    TEST_SERVICE_TOKEN,
    auth_headers,
    make_internal_envelope,
    make_valuation,
)

DATABASE_URL = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
RELEASE_TEST_RUNNER_KEY = Ed25519PrivateKey.from_private_bytes(b"r" * 32)
RELEASE_TEST_REVIEWER_KEY = Ed25519PrivateKey.from_private_bytes(b"v" * 32)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason=(
        "FUNDAMENTAL_TEST_DATABASE_URL is required for the PostgreSQL acceptance suite"
    ),
)


def _release_test_trust_roots() -> DataReleaseTrustRootsV1:
    return DataReleaseTrustRootsV1(
        verifiers={
            "postgres-test-runner": DataReleaseVerifierV1(
                workflow_identity="github://value-investment-agent/postgres-tests",
                public_key_ed25519_base64=base64.b64encode(
                    RELEASE_TEST_RUNNER_KEY.public_key().public_bytes_raw()
                ).decode("ascii"),
                verification_suite_digest="f" * 64,
            )
        },
        mapping_reviewers={
            "postgres-test-reviewer": base64.b64encode(
                RELEASE_TEST_REVIEWER_KEY.public_key().public_bytes_raw()
            ).decode("ascii")
        },
    )


def _snapshot(
    suffix: str,
    *,
    identity: IdentityV1 | None = None,
    valuation_timestamp: datetime | None = None,
    policy_version: str = "policy-v1",
    acquisition_key: str | None = None,
    taxonomy_manifest_id: str | None = None,
    validation_profile_id: str | None = None,
    validation_profile_digest: str | None = None,
    parser_version: str = "parser-v1",
) -> SourceSnapshotV1:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    source = SourceRecordV1(
        source_id="sec-companyfacts",
        uri=f"https://example.test/{suffix}",
        role=SourceRole.FILING,
        available_at=now,
        captured_at=now,
        http_status=200,
        media_type="application/json",
        terms_reference="sec-public",
        content_hash="a" * 64,
        parser_version="parser-v1",
    )
    identity = identity or IdentityV1(
        issuer_id="0000000001",
        issuer_name="Example Co",
        security_id="EXAMPLE-COMMON",
        share_class="COMMON",
        domicile="US",
        reporting_basis="us-gaap",
        currency="USD",
    )
    payload = {
        "contract_version": "fundamental.v1",
        "snapshot_id": f"snapshot-{suffix}",
        "identity": identity,
        "valuation_timestamp": valuation_timestamp or now,
        "fiscal_period_selector": FiscalPeriodSelectorV1(
            mode="latest_complete", count=3
        ),
        "resolved_fiscal_periods": (),
        "captured_at": now,
        "source_records": (source,),
        "taxonomy_manifest_id": taxonomy_manifest_id,
        "acquisition_key": acquisition_key,
        "validation_profile_id": validation_profile_id,
        "validation_profile_digest": validation_profile_digest,
        "parser_version": parser_version,
        "policy_version": policy_version,
        "coverage_status": QualityStatus.VERIFIED,
        "issues": (),
        "sec_integrity_evidence": None,
    }
    return SourceSnapshotV1(
        **payload,
        manifest_digest=sha256_digest(
            {key: value for key, value in payload.items() if key != "snapshot_id"}
        ),
    )


def _sec_ingestion_result(
    snapshot: SourceSnapshotV1,
    *,
    correlation_id: str,
    canonical_fact_ids: tuple[str, ...] = (),
) -> SecIngestionResponseV1:
    return SecIngestionResponseV1(
        contract_version="fundamental.v1",
        status="degraded",
        identity=snapshot.identity,
        valuation_timestamp=snapshot.valuation_timestamp,
        snapshot_id=snapshot.snapshot_id,
        manifest_digest=snapshot.manifest_digest,
        canonical_fact_ids=canonical_fact_ids,
        quality_status=QualityStatus.PROVISIONAL,
        parser_version=snapshot.parser_version,
        validation_profile_id=snapshot.validation_profile_id
        or "sec-efm-us-dqc-v31.0.3",
        validation_profile_digest=snapshot.validation_profile_digest or "b" * 64,
        taxonomy_manifest_id=snapshot.taxonomy_manifest_id or "taxonomy-test-v1",
        taxonomy_version="us-gaap-test-v1",
        correlation_id=correlation_id,
    )


def _sec_ingestion_request() -> SecIngestionRequestV1:
    return SecIngestionRequestV1(
        contract_version="fundamental.v1",
        identity=IdentityV1(
            issuer_id="0000789019",
            issuer_name="Microsoft Corporation",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="MSFT",
            share_class="common",
            currency="USD",
        ),
        cik="0000789019",
        ticker="MSFT",
        valuation_timestamp=datetime(2025, 6, 30, tzinfo=UTC),
        required_fields=("revenue",),
        mappings=(
            SecMappingReferenceV1(
                decision_id="sec-revenue-v1",
                mapping_version="sec-us-gaap-v1",
                normalized_field="revenue",
            ),
        ),
        source_selection_policy="sec-pit-v1",
        coverage_profile="us-gaap-public-v1",
        legal_use_profile="sec-public-us-v1",
        filing=SecFilingSelectorV1(accession_number="0000950170-24-087843"),
        parser_version="2.47.4",
        validation_profile_id="sec-efm-us-dqc-v31.0.3",
        taxonomy_manifest_id="sec-us-gaap-2023-2024-public-bundle",
        taxonomy_version="us-gaap-2023-2024",
        policy_version="sec-public-pit-v1",
    )


def _test_sec_acquisition_settings(request: SecIngestionRequestV1) -> SimpleNamespace:
    return SimpleNamespace(
        taxonomy_manifest_id=request.taxonomy_manifest_id,
        taxonomy_version=request.taxonomy_version,
        taxonomy_cache_sha256="c" * 64,
        supported_filing_years=(2023, 2024),
        supported_filing_forms=("10-K",),
        edgar_plugin_dir=Path("/runtime/arelle/EDGAR"),
        xule_plugin_dir=Path("/runtime/arelle/Xule"),
        dqc_ruleset_path=Path("/runtime/arelle/dqc-ruleset.xml"),
        edgar_plugin_sha256="a" * 64,
        xule_plugin_sha256="b" * 64,
        dqc_ruleset_sha256="d" * 64,
        dqc_ruleset_catalog=None,
    )


def _runtime_acquisition_payload(
    request: SecIngestionRequestV1, settings: SimpleNamespace | None = None
) -> dict[str, object]:
    use_case = object.__new__(SecAcquisitionUseCase)
    use_case.settings = settings or _test_sec_acquisition_settings(request)
    return use_case._runtime_key_payload(request, use_case._validation_profile(request))


def _fact_for_snapshot(snapshot: SourceSnapshotV1, fact_id: str) -> CanonicalFactV1:
    available = datetime(2025, 12, 1, tzinfo=UTC)
    period_start = datetime(2025, 1, 1, tzinfo=UTC).date()
    period_end = datetime(2025, 12, 31, tzinfo=UTC).date()
    return CanonicalFactV1(
        contract_version="fundamental.v1",
        fact_id=fact_id,
        issuer_id=snapshot.identity.issuer_id,
        security_id=snapshot.identity.security_id,
        concept="us-gaap:Revenues",
        normalized_field="revenue",
        value=Decimal(100),
        unit="USD",
        scale=0,
        currency="USD",
        period_start=period_start,
        period_end=period_end,
        context=XbrlContextV1(
            concept_qname="us-gaap:Revenues",
            period_type=PeriodType.DURATION,
            start_date=period_start,
            end_date=period_end,
            unit_qname="xbrli:shares",
            measure="iso4217:USD",
            entity_scope="consolidated",
            consolidation_scope="consolidated",
            context_id=fact_id,
        ),
        security_scope=snapshot.identity.security_id,
        as_of=datetime(2025, 12, 31, tzinfo=UTC),
        available_at=available,
        filed_at=available,
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
        accession_number="0000000001-25-000001",
        filing_version="original",
        taxonomy_version="us-gaap-test-v1",
        source=SourceProvenanceV1(
            source_url=snapshot.source_records[0].uri,
            content_hash=snapshot.source_records[0].content_hash,
            source_role=SourceRole.FILING,
            captured_at=datetime(2026, 1, 2, tzinfo=UTC),
            available_at=available,
            filed_at=available,
            accession_number="0000000001-25-000001",
            parser_version=snapshot.parser_version,
            taxonomy_version="us-gaap-test-v1",
            terms_reference="SEC fair access policy",
        ),
        quality=QualityStatus.PROVISIONAL,
    )


async def _update_coalescing_probe(
    metadata: PostgresMetadataStore,
    table: str,
    run_id: str,
    *,
    provider_call: bool,
    increment_attempts: bool = True,
) -> None:
    async with metadata._runner._engine.begin() as connection:
        if provider_call:
            await connection.execute(
                text(
                    f"UPDATE fundamental.{table} "
                    "SET provider_calls=provider_calls + 1 WHERE run_id=:run_id"
                ),
                {"run_id": run_id},
            )
        if increment_attempts:
            await connection.execute(
                text(
                    f"UPDATE fundamental.{table} "
                    "SET attempts=attempts + 1 WHERE run_id=:run_id"
                ),
                {"run_id": run_id},
            )


async def _coalescing_probe_attempts(
    metadata: PostgresMetadataStore, table: str, run_id: str
) -> int:
    async with metadata._runner._engine.connect() as connection:
        result = await connection.execute(
            text(f"SELECT attempts FROM fundamental.{table} WHERE run_id=:run_id"),
            {"run_id": run_id},
        )
        return int(result.scalar_one())


def _cross_process_ingestion_contenders(
    database_url: str,
    acquisition_key: str,
    acquisition_payload: dict[str, object],
    table: str,
    run_id: str,
    process_barrier,
    group_number: int,
) -> tuple[tuple[str, str, str], ...]:
    metadata = PostgresMetadataStore(database_url, auto_migrate=False)
    metadata.start()
    request = _sec_ingestion_request().model_copy(
        update={"policy_version": f"sec-public-pit-{run_id}"}
    )
    use_case = object.__new__(SecAcquisitionUseCase)
    use_case._original_reads = ContextVar("original_preparation_reads", default=None)
    use_case.capture_store = None
    use_case.metadata = metadata
    use_case.authorized_organizations = frozenset({"org-sec-ingestion-test"})
    use_case.settings = _test_sec_acquisition_settings(request)
    if (
        use_case._runtime_key_payload(request, use_case._validation_profile(request))
        != acquisition_payload
        or sha256_digest(acquisition_payload) != acquisition_key
    ):
        raise AssertionError("concurrent requests did not use the expected key")
    original_try_acquire = metadata.try_acquire_ingestion_lock

    def tracked_try_acquire(acquisition_key: str):
        lease = original_try_acquire(acquisition_key)
        metadata._runner.run(
            _update_coalescing_probe(
                metadata,
                table,
                run_id,
                provider_call=False,
                increment_attempts=True,
            )
        )
        return lease

    metadata.try_acquire_ingestion_lock = tracked_try_acquire

    def acquire_and_publish(
        acquisition_request: SecIngestionRequestV1,
        *,
        acquisition_key: str,
        key_payload: dict[str, object],
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
        validation_profile,
        prepared_filing=None,
    ) -> SecIngestionResponseV1:
        _ = deadline_at
        assert prepared_filing is None
        if (
            _runtime_acquisition_payload(acquisition_request, use_case.settings)
            != key_payload
            or validation_profile.digest()
            != key_payload["runtime_releases"]["validation_profile_digest"]
        ):
            raise AssertionError("request payload changed during acquisition")
        metadata._runner.run(
            _update_coalescing_probe(
                metadata,
                table,
                run_id,
                provider_call=True,
                increment_attempts=False,
            )
        )
        snapshot = _snapshot(
            f"issue312-{run_id}",
            identity=acquisition_request.identity,
            valuation_timestamp=acquisition_request.valuation_timestamp,
            acquisition_key=acquisition_key,
            taxonomy_manifest_id=acquisition_request.taxonomy_manifest_id,
            validation_profile_id=acquisition_request.validation_profile_id,
            validation_profile_digest="b" * 64,
            parser_version=acquisition_request.parser_version,
            policy_version=acquisition_request.policy_version,
        )
        result = _sec_ingestion_result(
            snapshot,
            correlation_id=correlation_id,
        )
        deadline = time.monotonic() + 30
        while (
            metadata._runner.run(_coalescing_probe_attempts(metadata, table, run_id))
            < 50
        ):
            if time.monotonic() >= deadline:
                raise TimeoutError("not all HTTP requests reached PostgreSQL")
            time.sleep(0.01)
        metadata.publish_sec_ingestion(
            acquisition_key=acquisition_key,
            acquisition_payload=key_payload,
            snapshot=snapshot,
            facts=(),
            result=result,
            caller_principal=caller_principal,
            organization_id=organization_id,
        )
        return result

    use_case._acquire_and_publish = acquire_and_publish
    app = create_app(
        config=OperationsConfig(
            service_token=TEST_SERVICE_TOKEN,
            rate_limit_per_minute=1_000,
            ingestion_rate_limit_per_minute=1_000,
        ),
        sec_acquisition=use_case,
    )
    group_ready = Barrier(6)
    start_group = Event()

    def contend(participant: int) -> tuple[str, str | None, str | None]:
        group_ready.wait(timeout=30)
        if not start_group.wait(timeout=30):
            raise TimeoutError("HTTP contenders were not released")
        correlation_id = f"race-{run_id}-{group_number}-{participant}"
        envelope = make_internal_envelope(
            request.model_dump(mode="json"),
            correlation_id=correlation_id,
            deadline_at=datetime.now(UTC) + timedelta(seconds=90),
            organization_id="org-sec-ingestion-test",
        )
        first_response = TestClient(app).post(
            "/v1/data/ingestions",
            headers=auth_headers(organization_id="org-sec-ingestion-test"),
            json=envelope,
        )
        if first_response.status_code == 200:
            first_body = first_response.json()["result"]
            first_outcome = "published"
            snapshot_id = first_body["snapshot_id"]
            manifest_digest = first_body["manifest_digest"]
        elif (
            first_response.status_code == 409
            and first_response.json()["error"]["code"] == "INGESTION_IN_PROGRESS"
        ):
            first_outcome = "ingestion_in_progress"
            snapshot_id = None
            manifest_digest = None
        else:
            raise AssertionError(
                f"unexpected first HTTP response {first_response.status_code}: "
                f"{first_response.text}"
            )

        return first_outcome, snapshot_id, manifest_digest

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(contend, index) for index in range(5)]
            group_ready.wait(timeout=30)
            process_barrier.wait(timeout=60)
            start_group.set()
            return tuple(future.result(timeout=60) for future in futures)
    finally:
        metadata.close()


def _hold_ingestion_lock_until_terminated(
    database_url: str,
    acquisition_key: str,
    acquired_event,
    release_event,
) -> None:
    metadata = PostgresMetadataStore(database_url, auto_migrate=False)
    metadata.start()
    lease = metadata.try_acquire_ingestion_lock(acquisition_key)
    if lease is None:
        metadata.close()
        raise AssertionError("child process could not acquire ingestion lock")
    acquired_event.set()
    try:
        release_event.wait(timeout=60)
    finally:
        metadata.release_ingestion_lock(lease)
        metadata.close()


@pytest.fixture
def metadata() -> PostgresMetadataStore:
    assert DATABASE_URL is not None
    store = PostgresMetadataStore(
        DATABASE_URL,
        auto_migrate=True,
        data_release_trust_roots=_release_test_trust_roots(),
    )
    store.start()
    yield store
    store.close()


def test_schema_and_snapshot_survive_restart(metadata: PostgresMetadataStore):
    snapshot = _snapshot(uuid4().hex)
    repository = PostgresSnapshotRepository(metadata)
    repository.publish(snapshot)
    assert metadata.health == type(metadata.health)(True, SCHEMA_VERSION)

    metadata.close()
    metadata.close()
    restarted = PostgresMetadataStore(DATABASE_URL or "", auto_migrate=False)
    restarted.start()
    try:
        assert (
            PostgresSnapshotRepository(restarted).get(snapshot.snapshot_id) == snapshot
        )
        assert restarted.health.schema_version == SCHEMA_VERSION
    finally:
        restarted.close()


def _data_release_candidate(
    suffix: str, *, profile_id: str | None = None
) -> tuple[DataReleaseManifestV1, DataReleaseVerificationV1]:
    fact_refs = ({"fact_id": f"fact-{suffix}", "fact_digest": "d" * 64},)
    taxonomy_ref = {
        "artifact_id": f"taxonomy-{suffix}",
        "content_hash": "b" * 64,
        "media_type": "application/zip",
        "role": "taxonomy",
    }
    evidence_ref = {
        "artifact_id": f"quality-evidence-{suffix}",
        "content_hash": "c" * 64,
        "media_type": "application/json",
        "role": "quality-evidence",
    }
    manifest_payload = {
        "profile_id": profile_id or f"sec-public-pit-{suffix}",
        "release_id": f"data-release-{suffix}",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "snapshot_refs": (
            {
                "snapshot_id": f"snapshot-{suffix}",
                "manifest_digest": "a" * 64,
                "facts": fact_refs,
                "fact_set_digest": sha256_digest(fact_refs),
            },
        ),
        "mapping_refs": (
            {"mapping_id": f"mapping-{suffix}", "mapping_digest": "e" * 64},
        ),
        "taxonomy_refs": (taxonomy_ref,),
        "parser_version": "arelle-release==2.47.4",
        "quality_profile_digest": "c" * 64,
        "required_fields": ("revenue",),
        "artifact_refs": (evidence_ref,),
    }
    manifest = DataReleaseManifestV1(
        **manifest_payload,
        manifest_digest=sha256_digest(manifest_payload),
    )
    mapping_review = sign_mapping_review_evidence(
        {
            "mapping_id": f"mapping-{suffix}",
            "mapping_digest": "e" * 64,
            "author_id": "mapping-builder",
            "reviewer_id": "postgres-test-reviewer",
            "reviewed_at": datetime(2026, 1, 1, tzinfo=UTC),
            "evidence_refs": (evidence_ref,),
            "fixture_digest": sha256_digest({"mapping": suffix}),
        },
        RELEASE_TEST_REVIEWER_KEY,
    )
    verification = sign_data_release_verification(
        {
            "manifest_digest": manifest.manifest_digest,
            "verification_suite_digest": "f" * 64,
            "source_revision": "0" * 40,
            "verification_run_id": f"postgres-release-{suffix}",
            "workflow_identity": "github://value-investment-agent/postgres-tests",
            "verifier_id": "postgres-test-runner",
            "passed_gate_ids": tuple(sorted(REQUIRED_DATA_RELEASE_GATES)),
            "evidence_refs": (evidence_ref,),
            "mapping_reviews": (mapping_review,),
        },
        RELEASE_TEST_RUNNER_KEY,
    )
    return manifest, verification


def _activation_command(
    manifest: DataReleaseManifestV1,
    *,
    command_id: str | None = None,
    expected_revision: int = 0,
    expected_manifest_digest: str | None = None,
    operation: str = "activate",
) -> DataReleaseActivationCommandV1:
    return DataReleaseActivationCommandV1(
        profile_id=manifest.profile_id,
        manifest_digest=manifest.manifest_digest,
        expected_revision=expected_revision,
        expected_manifest_digest=expected_manifest_digest,
        operation=operation,
        command_id=command_id or uuid4().hex,
        actor_id="release-operator",
        organization_id="org-fundamental-test",
        correlation_id=f"release-{uuid4().hex}",
        reason="PostgreSQL release activation test",
    )


def test_data_release_activation_is_fenced_and_v2_compatible(
    metadata: PostgresMetadataStore,
):
    manifest, verification = _data_release_candidate(uuid4().hex)
    metadata.publish_data_release_candidate(manifest, verification)
    metadata.publish_data_release_candidate(manifest, verification)
    assert metadata.get_data_release_manifest(manifest.manifest_digest) == manifest
    assert (
        metadata.get_data_release_verification(manifest.manifest_digest) == verification
    )
    assert metadata.get_data_release_verification("0" * 64) is None
    command = _activation_command(manifest)

    active = metadata.compare_and_swap_data_release(command)
    assert active.profile_id == manifest.profile_id
    assert active.manifest_digest == manifest.manifest_digest
    assert active.revision == 1
    resolved = metadata.get_active_data_release_with_manifest(manifest.profile_id)
    assert resolved is not None
    assert resolved.active == active
    assert resolved.manifest == manifest
    assert metadata.get_data_release_manifest(manifest.manifest_digest) == manifest
    assert metadata.compare_and_swap_data_release(command) == active
    altered_retry = command.model_copy(update={"reason": "different command"})
    with pytest.raises(DataReleaseError) as idempotency_conflict:
        metadata.compare_and_swap_data_release(altered_retry)
    assert idempotency_conflict.value.code == "DATA_RELEASE_IDEMPOTENCY_CONFLICT"

    stale = _activation_command(
        manifest,
        expected_revision=0,
        expected_manifest_digest=None,
    )
    with pytest.raises(DataReleaseError) as conflict:
        metadata.compare_and_swap_data_release(stale)
    assert conflict.value.code == "DATA_RELEASE_POINTER_CONFLICT"
    assert metadata.get_active_data_release(manifest.profile_id) == active

    async def read_release_schema() -> tuple[int, int, int]:
        async with metadata._runner._engine.connect() as connection:
            version_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.schema_migrations "
                    "WHERE version=:version"
                ),
                {"version": SCHEMA_VERSION},
            )
            capability_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.schema_capabilities "
                    "WHERE capability_id='data-release-activation-v1'"
                )
            )
            audit_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.data_release_activation_audit "
                    "WHERE profile_id=:profile_id"
                ),
                {"profile_id": manifest.profile_id},
            )
        return (
            int(version_count or 0),
            int(capability_count or 0),
            int(audit_count or 0),
        )

    assert metadata.health.schema_version == SCHEMA_VERSION
    assert metadata._runner.run(read_release_schema()) == (1, 1, 1)

    old_version_reader = PostgresMetadataStore(DATABASE_URL or "", auto_migrate=False)
    old_version_reader.start()
    try:
        assert old_version_reader.health.schema_version == SCHEMA_VERSION
        assert old_version_reader.get_active_data_release(manifest.profile_id) == active
    finally:
        old_version_reader.close()


@pytest.mark.parametrize(
    "fault,code",
    (
        ("signature", "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID"),
        ("row_digest", "DATA_RELEASE_VERIFICATION_MISMATCH"),
        ("manifest", "DATA_RELEASE_VERIFICATION_MISMATCH"),
        ("closure", "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID"),
        ("mapping_signature", "DATA_RELEASE_MAPPING_REVIEW_SIGNATURE_INVALID"),
    ),
)
def test_retained_release_verification_requires_current_trust(
    metadata: PostgresMetadataStore, fault: str, code: str
):
    manifest, verification = _data_release_candidate(uuid4().hex)
    metadata.publish_data_release_candidate(manifest, verification)
    payload = verification.model_dump(mode="json")
    row_digest = verification.verification_digest
    if fault == "signature":
        payload["signature"] = "0" * 128
    elif fault == "row_digest":
        row_digest = "0" * 64
    else:
        unsigned = verification.model_dump(
            mode="python", exclude={"signature", "verification_digest"}
        )
        if fault == "manifest":
            unsigned["manifest_digest"] = "0" * 64
        elif fault == "closure":
            unsigned["evidence_refs"] = (
                verification.evidence_refs[0].model_copy(
                    update={"artifact_id": "substituted-verification-evidence"}
                ),
            )
        else:
            review = verification.mapping_reviews[0].model_copy(
                update={"signature": "0" * 128}
            )
            unsigned["mapping_reviews"] = (review,)
        changed = sign_data_release_verification(unsigned, RELEASE_TEST_RUNNER_KEY)
        payload = changed.model_dump(mode="json")
        row_digest = changed.verification_digest
        if fault == "closure":
            payload["signature"] = verification.signature

    async def corrupt() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE fundamental.data_release_verifications "
                    "SET payload=CAST(:payload AS jsonb), verification_digest=:digest "
                    "WHERE manifest_digest=:manifest"
                ),
                {
                    "payload": json.dumps(payload),
                    "digest": row_digest,
                    "manifest": manifest.manifest_digest,
                },
            )

    metadata._runner.run(corrupt())
    with pytest.raises(DataReleaseError) as error:
        metadata.get_data_release_verification(manifest.manifest_digest)
    assert error.value.code == code


def test_data_release_candidate_is_not_persisted_without_trust_roots():
    assert DATABASE_URL is not None
    metadata = PostgresMetadataStore(DATABASE_URL, auto_migrate=True)
    metadata.start()
    manifest, verification = _data_release_candidate(uuid4().hex)

    try:
        with pytest.raises(DataReleaseError) as unconfigured:
            metadata.publish_data_release_candidate(manifest, verification)
        assert unconfigured.value.code == "DATA_RELEASE_TRUST_ROOTS_UNCONFIGURED"

        async def candidate_count() -> int:
            async with metadata._runner._engine.connect() as connection:
                count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM fundamental.data_release_manifests "
                        "WHERE manifest_digest=:digest"
                    ),
                    {"digest": manifest.manifest_digest},
                )
            return int(count or 0)

        assert metadata._runner.run(candidate_count()) == 0
    finally:
        metadata.close()


def test_data_release_candidate_transaction_rolls_back_after_manifest_insert(
    metadata: PostgresMetadataStore,
):
    manifest, verification = _data_release_candidate(uuid4().hex)
    suffix = uuid4().hex
    function_name = f"reject_release_verification_{suffix}"
    trigger_name = f"reject_release_verification_trigger_{suffix}"

    async def install_failure_trigger() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    f"CREATE FUNCTION fundamental.{function_name}() "
                    "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                    "RAISE EXCEPTION 'injected release verification failure'; END $$"
                )
            )
            await connection.execute(
                text(
                    f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON "
                    "fundamental.data_release_verifications "
                    f"FOR EACH ROW EXECUTE FUNCTION fundamental.{function_name}()"
                )
            )

    async def remove_failure_trigger() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    "DROP TRIGGER IF EXISTS "
                    f"{trigger_name} ON fundamental.data_release_verifications"
                )
            )
            await connection.execute(
                text(f"DROP FUNCTION IF EXISTS fundamental.{function_name}()")
            )

    async def persisted_counts() -> tuple[int, int]:
        async with metadata._runner._engine.connect() as connection:
            manifest_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.data_release_manifests "
                    "WHERE manifest_digest=:digest"
                ),
                {"digest": manifest.manifest_digest},
            )
            verification_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.data_release_verifications "
                    "WHERE manifest_digest=:digest"
                ),
                {"digest": manifest.manifest_digest},
            )
        return int(manifest_count or 0), int(verification_count or 0)

    metadata._runner.run(install_failure_trigger())
    try:
        with pytest.raises(DBAPIError, match="injected release verification failure"):
            metadata.publish_data_release_candidate(manifest, verification)
    finally:
        metadata._runner.run(remove_failure_trigger())

    assert metadata._runner.run(persisted_counts()) == (0, 0)
    metadata.publish_data_release_candidate(manifest, verification)
    assert metadata.get_data_release_manifest(manifest.manifest_digest) == manifest


def test_data_release_audit_failure_rolls_back_pointer_and_can_retry(
    metadata: PostgresMetadataStore,
):
    manifest, verification = _data_release_candidate(uuid4().hex)
    metadata.publish_data_release_candidate(manifest, verification)
    command = _activation_command(manifest)
    suffix = uuid4().hex
    function_name = f"reject_release_audit_{suffix}"
    trigger_name = f"reject_release_audit_trigger_{suffix}"

    async def install_failure_trigger() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    f"CREATE FUNCTION fundamental.{function_name}() "
                    "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                    "RAISE EXCEPTION 'injected release audit failure'; END $$"
                )
            )
            await connection.execute(
                text(
                    f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON "
                    "fundamental.data_release_activation_audit "
                    f"FOR EACH ROW EXECUTE FUNCTION fundamental.{function_name}()"
                )
            )

    async def remove_failure_trigger() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    "DROP TRIGGER IF EXISTS "
                    f"{trigger_name} ON fundamental.data_release_activation_audit"
                )
            )
            await connection.execute(
                text(f"DROP FUNCTION IF EXISTS fundamental.{function_name}()")
            )

    metadata._runner.run(install_failure_trigger())
    try:
        with pytest.raises(DBAPIError, match="injected release audit failure"):
            metadata.compare_and_swap_data_release(command)
    finally:
        metadata._runner.run(remove_failure_trigger())

    assert metadata.get_active_data_release(manifest.profile_id) is None

    async def audit_count() -> int:
        async with metadata._runner._engine.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.data_release_activation_audit "
                    "WHERE profile_id=:profile_id"
                ),
                {"profile_id": manifest.profile_id},
            )
        return int(count or 0)

    assert metadata._runner.run(audit_count()) == 0
    assert metadata.compare_and_swap_data_release(command).revision == 1


def test_competing_data_release_publishers_share_one_revision(
    metadata: PostgresMetadataStore,
):
    profile_id = f"sec-public-pit-race-{uuid4().hex}"
    candidates = tuple(
        _data_release_candidate(uuid4().hex, profile_id=profile_id) for _ in range(2)
    )
    for manifest, verification in candidates:
        metadata.publish_data_release_candidate(manifest, verification)

    barrier = Barrier(2)

    def activate(manifest: DataReleaseManifestV1) -> tuple[str, str]:
        barrier.wait(timeout=10)
        try:
            result = metadata.compare_and_swap_data_release(
                _activation_command(manifest)
            )
            return "activated", result.manifest_digest
        except DataReleaseError as exc:
            return "conflict", exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(activate, (candidate[0] for candidate in candidates))
        )

    assert sorted(result[0] for result in results) == ["activated", "conflict"]
    active = metadata.get_active_data_release(candidates[0][0].profile_id)
    assert active is not None
    assert active.revision == 1
    assert active.manifest_digest in {
        candidate[0].manifest_digest for candidate in candidates
    }

    async def audit_count() -> int:
        async with metadata._runner._engine.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM fundamental.data_release_activation_audit "
                    "WHERE profile_id=:profile_id"
                ),
                {"profile_id": active.profile_id},
            )
        return int(count or 0)

    assert metadata._runner.run(audit_count()) == 1


def test_data_release_pointer_survives_restart_and_legacy_reader_overlap(
    metadata: PostgresMetadataStore,
):
    profile_id = f"sec-public-pit-overlap-{uuid4().hex}"
    first, first_verification = _data_release_candidate(
        uuid4().hex, profile_id=profile_id
    )
    second, second_verification = _data_release_candidate(
        uuid4().hex, profile_id=profile_id
    )
    metadata.publish_data_release_candidate(first, first_verification)
    metadata.publish_data_release_candidate(second, second_verification)
    first_active = metadata.compare_and_swap_data_release(_activation_command(first))

    legacy_reader = PostgresMetadataStore(DATABASE_URL or "", auto_migrate=False)
    legacy_reader.start()
    try:
        second_active = metadata.compare_and_swap_data_release(
            _activation_command(
                second,
                expected_revision=first_active.revision,
                expected_manifest_digest=first_active.manifest_digest,
            )
        )
        assert legacy_reader.health.schema_version == SCHEMA_VERSION
        assert legacy_reader.get_active_data_release(profile_id) == second_active
    finally:
        legacy_reader.close()

    metadata.close()
    restarted = PostgresMetadataStore(DATABASE_URL or "", auto_migrate=False)
    restarted.start()
    try:
        assert restarted.get_active_data_release(profile_id) == second_active
        rolled_back = restarted.compare_and_swap_data_release(
            _activation_command(
                first,
                expected_revision=second_active.revision,
                expected_manifest_digest=second_active.manifest_digest,
                operation="rollback",
            )
        )
        assert rolled_back.revision == second_active.revision + 1
        assert rolled_back.manifest_digest == first.manifest_digest
    finally:
        restarted.close()


def test_snapshot_metadata_is_immutable(metadata: PostgresMetadataStore):
    suffix = uuid4().hex
    repository = PostgresSnapshotRepository(metadata)
    repository.publish(_snapshot(suffix))
    with pytest.raises(SnapshotError, match="immutable"):
        repository.publish(_snapshot(suffix, policy_version="policy-v2"))


def test_postgres_sec_request_slot_matches_source_adapter_callback(
    metadata: PostgresMetadataStore,
):
    class FakeResponse:
        status = 200

        def __init__(self):
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

        def read(self) -> bytes:
            return b'{"entityName":"Example Co"}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_response(_request, timeout):
        assert timeout > 0
        return FakeResponse()

    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=open_response,
        request_slot=metadata.reserve_sec_provider_request_slot,
    )

    source = adapter.capture_company_facts("0000320193")

    assert source.source_id == "sec-companyfacts"


@pytest.mark.parametrize(
    ("entry", "statement_fragment"),
    [
        ("capture", "SELECT pg_try_advisory_lock"),
        ("index", "INSERT INTO fundamental.parser_action_results"),
        ("pacing", "UPDATE fundamental.sec_provider_rate_limits"),
    ],
)
def test_fiscal_metadata_entries_share_deadline(
    metadata, tmp_path, monkeypatch, entry, statement_fragment
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    action_key = sha256_digest(uuid4().hex)
    artifact_id = f"fiscal-operation-budget-{action_key}"
    artifacts.put_with_receipt(artifact_id, {"value": "immutable"})
    acquisition = SimpleNamespace(metadata=metadata)
    acquisition._capture_lock = SecAcquisitionUseCase._capture_lock.__get__(acquisition)
    sql_started, sql_cancelled = Event(), Event()
    connection_returned = Event()
    opened = False
    execute = AsyncConnection.execute

    async def slow_sql(connection, statement, *args, **kwargs):
        result = await execute(connection, statement, *args, **kwargs)
        if statement_fragment in str(statement) and not sql_started.is_set():
            sql_started.set()
            try:
                await execute(connection, text("SELECT pg_sleep(1.5)"))
            except asyncio.CancelledError:
                sql_cancelled.set()
                raise
        return result

    def checked_in(*_args):
        if sql_started.is_set():
            connection_returned.set()

    def open_response(_request, *, timeout):
        nonlocal opened
        opened = True
        raise AssertionError(f"HTTP opened with stale remaining time {timeout}")

    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=open_response,
        request_slot=metadata.reserve_sec_provider_request_slot,
    )
    monkeypatch.setattr(AsyncConnection, "execute", slow_sql)
    pool = metadata._runner._engine.sync_engine.pool
    event.listen(pool, "checkin", checked_in)
    try:
        start = time.monotonic()
        deadline = datetime.now(UTC) + timedelta(seconds=0.35)
        with (
            SecAcquisitionUseCase._fiscal_metadata_operation(deadline),
            pytest.raises(SecSourceError, match="deadline"),
        ):
            if entry == "capture":
                with acquisition._capture_lock(action_key):
                    pytest.fail("expired capture lock entered source acquisition")
            elif entry == "index":
                metadata.publish_parser_action_result(action_key, artifact_id)
            else:
                adapter.capture_company_facts("0000320193", deadline_at=deadline)
        assert time.monotonic() - start < 1, "caller waited for the untimed SQL"
        assert sql_started.is_set()
        assert sql_cancelled.wait(3), "PostgreSQL wait was never cancelled"
        assert connection_returned.wait(3), "cancelled connection was never returned"
    finally:
        event.remove(pool, "checkin", checked_in)
    assert not opened
    assert metadata.parser_action_result(action_key) is None
    lease = metadata.try_acquire_ingestion_lock(action_key)
    assert lease is not None
    metadata.release_ingestion_lock(lease)
    metadata.publish_parser_action_result(action_key, artifact_id)
    metadata.publish_parser_action_result(action_key, artifact_id)
    assert metadata.parser_action_result(action_key) == artifact_id


def test_fiscal_index_checks_deadline_at_commit(metadata, tmp_path, monkeypatch):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    action_key = sha256_digest(uuid4().hex)
    artifact_id = f"fiscal-operation-commit-{action_key}"
    artifacts.put_with_receipt(artifact_id, {"value": "immutable"})
    expired = Event()
    exit_transaction = AsyncTransaction.__aexit__

    async def expire_at_commit(transaction, exc_type, exc_value, traceback):
        if exc_type is None and not expired.is_set():
            expired.set()
        return await exit_transaction(transaction, exc_type, exc_value, traceback)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncTransaction, "__aexit__", expire_at_commit)
        with (
            metadata_operation_budget(
                lambda: 0 if expired.is_set() else 3, sec_deadline_exceeded
            ),
            pytest.raises(SecSourceError, match="deadline"),
        ):
            metadata.publish_parser_action_result(action_key, artifact_id)

    assert metadata.parser_action_result(action_key) is None
    metadata.publish_parser_action_result(action_key, artifact_id)
    metadata.publish_parser_action_result(action_key, artifact_id)
    assert metadata.parser_action_result(action_key) == artifact_id


def test_fiscal_metadata_scopes_isolate_actors_and_release_expired_lease(metadata):
    first_key = sha256_digest(uuid4().hex)
    second_key = sha256_digest(uuid4().hex)
    first_expired = Event()
    both_started = Barrier(2, timeout=3)

    def first_actor():
        with metadata_operation_budget(
            lambda: 0 if first_expired.is_set() else 3, sec_deadline_exceeded
        ):
            lease = metadata.try_acquire_ingestion_lock(first_key)
            assert lease is not None
            first_expired.set()
            both_started.wait()
            with (
                metadata_operation_budget(lambda: 5, sec_deadline_exceeded),
                pytest.raises(SecSourceError, match="deadline"),
            ):
                metadata.try_acquire_ingestion_lock(second_key)
            metadata.release_ingestion_lock(lease)
            with pytest.raises(SecSourceError, match="deadline"):
                metadata.parser_action_result(first_key)
        return metadata.try_acquire_ingestion_lock(first_key)

    def second_actor():
        with metadata_operation_budget(lambda: 5, sec_deadline_exceeded):
            both_started.wait()
            lease = metadata.try_acquire_ingestion_lock(second_key)
            assert lease is not None
            metadata.release_ingestion_lock(lease)
        assert metadata.parser_action_result(second_key) is None

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_actor)
        second = executor.submit(second_actor)
        lease = first.result(timeout=5)
        second.result(timeout=5)
    assert lease is not None
    metadata.release_ingestion_lock(lease)


def test_fiscal_metadata_close_completes_cancelled_lock_cleanup(metadata, monkeypatch):
    acquisition_key = sha256_digest(uuid4().hex)
    execute = AsyncConnection.execute
    cancellation_finished = Event()

    async def slow_lock(connection, statement, *args, **kwargs):
        result = await execute(connection, statement, *args, **kwargs)
        if str(statement).startswith("SELECT pg_try_advisory_lock"):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                await asyncio.sleep(0.15)
                cancellation_finished.set()
                raise
        return result

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "execute", slow_lock)
        with (
            SecAcquisitionUseCase._fiscal_metadata_operation(
                datetime.now(UTC) + timedelta(seconds=0.35)
            ),
            pytest.raises(SecSourceError, match="deadline"),
        ):
            metadata.try_acquire_ingestion_lock(acquisition_key)
        metadata.close()

    assert cancellation_finished.is_set()
    assert DATABASE_URL is not None
    observer = PostgresMetadataStore(DATABASE_URL)
    observer.start()
    try:
        lease = observer.try_acquire_ingestion_lock(acquisition_key)
        assert lease is not None
        observer.release_ingestion_lock(lease)
    finally:
        observer.close()


def test_versioned_releases_and_mappings_are_durable_and_immutable(
    metadata: PostgresMetadataStore,
):
    model = initial_model_specs()[0]
    metadata.publish_model(
        model, model_id=model.model_id, model_version=model.model_version
    )
    assert metadata.get_model(model.model_id, model.model_version) == model

    request = make_valuation()
    policy_payload = {
        "contract_version": "fundamental.v1",
        "policy_id": f"policy-postgres-{model.model_version}",
        "policy_version": f"policy-postgres-{model.model_version}",
        "profile_id": "us-gaap-public-v1",
        "model_id": model.model_id,
        "model_version": model.model_version,
        "assumptions": request.assumptions,
        "source_refs": ("public-policy",),
        "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
        "status": "active",
    }
    policy = PolicyRecordV1(
        **policy_payload, policy_digest=sha256_digest(policy_payload)
    )
    metadata.publish_policy(
        policy, policy_id=policy.policy_id, policy_version=policy.policy_version
    )
    assert metadata.get_policy(policy.policy_id, policy.policy_version) == policy

    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="mapping-postgres-v1",
        source_concept="us-gaap:Revenue",
        normalized_field="revenue",
        mapping_version="mapping-v1",
        confidence="high",
        status="approved",
    )
    metadata.publish_mapping(mapping)
    assert metadata.get_mapping(mapping.decision_id) == mapping

    with pytest.raises(SnapshotError, match="immutable"):
        metadata.publish_mapping(mapping.model_copy(update={"mapping_version": "v2"}))


def test_schema_mismatch_fails_readiness_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    assert DATABASE_URL is not None
    store = PostgresMetadataStore(DATABASE_URL, auto_migrate=False)

    async def stale_schema() -> str:
        return "stale-schema"

    monkeypatch.setattr(store, "_schema_version", stale_schema)
    try:
        with pytest.raises(SnapshotError, match="unavailable"):
            store.start()
        assert store.ready is False
        assert store.health.schema_version is None
    finally:
        store.close()


def test_artifact_publication_is_concurrent_and_hash_verified(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    artifact_id = f"artifact-{uuid4().hex}"

    def publish():
        return artifacts.put_with_receipt(artifact_id, {"value": "immutable"})

    with ThreadPoolExecutor(max_workers=6) as executor:
        receipts = tuple(executor.map(lambda _: publish(), range(12)))
    assert sum(receipt.wrote for receipt in receipts) == 1
    assert len({receipt.artifact.content_hash for receipt in receipts}) == 1
    assert artifacts.read(artifact_id) == b'{"value":"immutable"}'

    record = artifacts.get(artifact_id)
    path = content._filesystem._path(record.content_hash, record.media_type)
    original_mtime = path.stat().st_mtime_ns
    restarted = PostgresMetadataStore(DATABASE_URL or "", auto_migrate=False)
    restarted.start()
    try:
        restarted_artifacts = PostgresArtifactStore(
            restarted, PostgresContentStore(tmp_path / "content", restarted)
        )
        repeated = restarted_artifacts.put_with_receipt(
            artifact_id, {"value": "immutable"}
        )
        assert repeated.artifact == record
        assert repeated.wrote is False
        assert path.stat().st_mtime_ns == original_mtime
    finally:
        restarted.close()

    with pytest.raises(SnapshotError) as conflict:
        artifacts.put_with_receipt(
            artifact_id, {"value": "immutable"}, dependency_hashes=("f" * 64,)
        )
    assert conflict.value.code == "ARTIFACT_ID_REUSED"
    assert path.stat().st_mtime_ns == original_mtime

    path.write_bytes(b"tampered")
    with pytest.raises(SnapshotError, match="verification"):
        artifacts.read(artifact_id)
    with pytest.raises(SnapshotError):
        publish()
    assert path.read_bytes() == b"tampered"


@pytest.mark.parametrize(
    "when", ["after_insert", "before_commit", "during_sql", "during_commit_wait"]
)
def test_artifact_publication_rolls_back_when_deadline_expires(
    metadata, tmp_path, monkeypatch, when
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    artifact_id = f"artifact-deadline-{uuid4().hex}"
    payload = {"value": "immutable"}
    now = datetime.now(UTC)
    short_budget = when in {"during_sql", "during_commit_wait"}
    deadline = now + (timedelta(seconds=1) if short_budget else timedelta(minutes=1))
    execute = AsyncConnection.execute
    exit_transaction = AsyncTransaction.__aexit__
    inserted = False
    commit_wait_cancelled = False

    async def expire_after_insert(connection, statement, parameters=None, **kwargs):
        nonlocal now, inserted
        result = await execute(connection, statement, parameters, **kwargs)
        if (
            str(statement).startswith("INSERT INTO fundamental.artifact_references")
            and parameters
            and parameters["artifact_id"] == artifact_id
        ):
            assert result.rowcount == 1
            inserted = True
            if when == "after_insert":
                now = deadline
            elif when == "during_sql":
                await execute(connection, text("SELECT pg_sleep(5)"))
        return result

    async def expire_before_commit(transaction, exc_type, exc_value, traceback):
        nonlocal now, commit_wait_cancelled
        if when == "before_commit" and inserted and exc_type is None:
            now = deadline
        elif when == "during_commit_wait" and inserted and exc_type is None:
            try:
                await execute(transaction.connection, text("SELECT pg_sleep(5)"))
            except asyncio.CancelledError:
                commit_wait_cancelled = True
                raise
            now = deadline
        return await exit_transaction(transaction, exc_type, exc_value, traceback)

    def remaining():
        return (deadline - now).total_seconds()

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "execute", expire_after_insert)
        patch.setattr(AsyncTransaction, "__aexit__", expire_before_commit)
        if when == "during_commit_wait":
            run = metadata._runner.run

            def run_with_legacy_wait(coroutine, **kwargs):
                return run(coroutine)

            patch.setattr(metadata._runner, "run", run_with_legacy_wait)
        try:
            artifacts.put_with_receipt(
                artifact_id, payload, publication_budget=remaining
            )
        except ArtifactPublicationDeadlineExceeded as expired:
            assert expired.code == "REQUEST_DEADLINE_EXCEEDED"
        else:
            persisted = artifacts.get(artifact_id)
            pytest.fail(f"expired publication committed metadata: {persisted}")
    assert inserted
    if when == "during_commit_wait":
        assert commit_wait_cancelled, "the pre-commit SQL wait ran past the deadline"
    with pytest.raises(SnapshotError) as missing:
        artifacts.get(artifact_id)
    assert missing.value.code == "ARTIFACT_NOT_FOUND"

    deadline += timedelta(minutes=1)
    published = artifacts.put_with_receipt(
        artifact_id, payload, publication_budget=remaining
    )
    assert published.wrote
    assert artifacts.read(artifact_id) == b'{"value":"immutable"}'

    now = deadline
    with pytest.raises(ArtifactPublicationDeadlineExceeded):
        artifacts.put_with_receipt(artifact_id, payload, publication_budget=remaining)
    deadline += timedelta(minutes=1)
    assert (
        artifacts.put_with_receipt(
            artifact_id, payload, publication_budget=remaining
        ).artifact
        == published.artifact
    )
    assert not artifacts.put_with_receipt(
        artifact_id, payload, publication_budget=remaining
    ).wrote


def test_artifact_publication_bridge_cancels_exhausted_wait(
    metadata, tmp_path, monkeypatch
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    artifact_id = f"artifact-bridge-deadline-{uuid4().hex}"
    payload = {"value": "immutable"}
    exit_transaction = AsyncTransaction.__aexit__
    submit = asyncio.run_coroutine_threadsafe
    submitted = None
    entered_commit_wait = Event()
    release_event_loop = Event()
    event_loop_wait_expired = Event()
    commit_wait_cancelled = Event()
    connection_returned = Event()

    def track_submission(coroutine, loop):
        nonlocal submitted
        submitted = submit(coroutine, loop)
        return submitted

    async def block_before_commit(transaction, exc_type, exc_value, traceback):
        if exc_type is None and not entered_commit_wait.is_set():
            result = await transaction.connection.execute(
                text(
                    "SELECT 1 FROM fundamental.artifact_references "
                    "WHERE artifact_id=:artifact_id"
                ),
                {"artifact_id": artifact_id},
            )
            if result.scalar_one_or_none() is not None:
                entered_commit_wait.set()
                if not release_event_loop.wait(timeout=5):
                    event_loop_wait_expired.set()
                try:
                    await asyncio.sleep(0)
                except asyncio.CancelledError:
                    commit_wait_cancelled.set()
                    raise
        return await exit_transaction(transaction, exc_type, exc_value, traceback)

    def track_checkin(*args):
        if entered_commit_wait.is_set():
            connection_returned.set()

    with monkeypatch.context() as patch:
        patch.setattr(asyncio, "run_coroutine_threadsafe", track_submission)
        patch.setattr(AsyncTransaction, "__aexit__", block_before_commit)
        pool = metadata._runner._engine.sync_engine.pool
        event.listen(pool, "checkin", track_checkin)
        deadline = time.monotonic() + 1
        try:
            try:
                with pytest.raises(ArtifactPublicationDeadlineExceeded) as expired:
                    artifacts.put_with_receipt(
                        artifact_id,
                        payload,
                        publication_budget=lambda: deadline - time.monotonic(),
                    )
                assert expired.value.code == "REQUEST_DEADLINE_EXCEEDED"
                assert entered_commit_wait.is_set()
                assert not event_loop_wait_expired.is_set(), (
                    "the synchronous caller waited for the blocked event loop"
                )
                assert submitted is not None and submitted.cancelled()
            finally:
                release_event_loop.set()
            assert commit_wait_cancelled.wait(timeout=5)
            assert connection_returned.wait(timeout=5)
        finally:
            event.remove(pool, "checkin", track_checkin)

    with pytest.raises(SnapshotError) as missing:
        artifacts.get(artifact_id)
    assert missing.value.code == "ARTIFACT_NOT_FOUND"
    assert artifacts.put_with_receipt(artifact_id, payload).wrote
    assert not artifacts.put_with_receipt(artifact_id, payload).wrote


@pytest.mark.parametrize("fault", ("status", "dependency", "missing"))
def test_retained_artifact_operation_rejects_metadata_changes(
    metadata: PostgresMetadataStore, tmp_path: Path, fault: str
):
    from fundamental_service.artifact_evidence import read_retained_artifact
    from fundamental_service.data_releases import ArtifactRefV1

    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    record = artifacts.put(f"batch-{uuid4().hex}", {"retained": True})
    ref = ArtifactRefV1(
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
        role="retained-test",
    )

    async def change() -> None:
        async with metadata._runner._engine.begin() as connection:
            query = (
                "DELETE FROM fundamental.artifact_references WHERE artifact_id=:id"
                if fault == "missing"
                else "UPDATE fundamental.artifact_references "
                + (
                    "SET status='invalidated' "
                    if fault == "status"
                    else "SET dependency_hashes=CAST(:dependencies AS jsonb) "
                )
                + "WHERE artifact_id=:id"
            )
            await connection.execute(
                text(query),
                {"id": record.artifact_id, "dependencies": json.dumps(["f" * 64])},
            )

    with pytest.raises(DataReleaseError) as error:
        with artifacts.retained_read_operation((record.artifact_id,)) as reader:
            assert read_retained_artifact(reader, ref) == b'{"retained":true}'
            metadata._runner.run(change())
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    with pytest.raises(RuntimeError, match="ended"):
        reader.read(record.artifact_id)


def test_retained_artifact_operation_rechecks_bytes_and_indirect_records(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    first = artifacts.put(f"batch-{uuid4().hex}", {"first": True})
    indirect = artifacts.put(f"batch-{uuid4().hex}", {"indirect": True})
    with artifacts.retained_read_operation((first.artifact_id,)) as reader:
        assert reader.get(first.artifact_id) == first
        assert reader.read(indirect.artifact_id) == b'{"indirect":true}'
    path = content._filesystem._path(indirect.content_hash, indirect.media_type)
    path.write_bytes(b"corrupt")
    with pytest.raises(SnapshotError, match="verification"):
        with artifacts.retained_read_operation((first.artifact_id,)) as reader:
            reader.read(indirect.artifact_id)


@pytest.mark.parametrize("failure_at", ("entry", "exit", "body"))
def test_retained_artifact_operation_preserves_failure_reasons(
    metadata: PostgresMetadataStore, tmp_path: Path, monkeypatch, failure_at: str
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    record = artifacts.put(f"batch-{uuid4().hex}", {"retained": True})
    original = metadata.retained_artifact_records
    calls = []

    def unavailable(ids):
        calls.append(ids)
        if failure_at == "entry" or len(calls) == 2:
            raise TimeoutError("controlled metadata failure")
        return original(ids)

    monkeypatch.setattr(metadata, "retained_artifact_records", unavailable)
    expected = SnapshotError if failure_at == "body" else DataReleaseError
    with pytest.raises(expected) as error:
        with artifacts.retained_read_operation((record.artifact_id,)) as reader:
            if failure_at == "body":
                raise SnapshotError("SOURCE_HASH_MISMATCH", "controlled byte failure")
            assert reader.read(record.artifact_id) == b'{"retained":true}'
    assert error.value.code == (
        "SOURCE_HASH_MISMATCH"
        if failure_at == "body"
        else "DATA_RELEASE_ARTIFACT_UNAVAILABLE"
    )
    if failure_at == "body":
        assert len(calls) == 1


def _change_artifact_metadata(metadata, query, parameters):
    async def change():
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(text(query), parameters)

    metadata._runner.run(change())


def test_current_records_observes_fresh_absence_and_metadata_without_registration(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    record = artifacts.put(uuid4().hex, {"retained": uuid4().hex})
    absent = tuple((uuid4().hex, None) for _ in range(4095))
    expected = (*absent, (record.artifact_id, record))
    readonly = artifacts.as_read_only()
    readonly.require_current_records(expected, check_deadline=lambda: None)
    _change_artifact_metadata(
        metadata,
        "DELETE FROM fundamental.content_objects "
        "WHERE content_hash=:hash AND media_type=:media",
        {"hash": record.content_hash, "media": record.media_type},
    )
    readonly.require_current_records(expected, check_deadline=lambda: None)
    with pytest.raises(SnapshotError) as missing_registration:
        metadata.content_byte_length(record.content_hash, media_type=record.media_type)
    assert missing_registration.value.code == "CONTENT_REGISTRATION_UNAVAILABLE"
    artifacts.put(absent[0][0], {"appeared": uuid4().hex})
    with pytest.raises(DataReleaseError) as changed:
        readonly.require_current_records(expected, check_deadline=lambda: None)
    assert changed.value.code == "ARTIFACT_EVIDENCE_CHANGED"


def test_current_records_does_not_reuse_an_active_scoped_starting_record(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    record = artifacts.put(uuid4().hex, {"retained": uuid4().hex})
    readonly = artifacts.as_read_only()
    with pytest.raises(DataReleaseError) as changed:
        with readonly.scoped_read_operation():
            assert readonly.get(record.artifact_id) == record
            _change_artifact_metadata(
                metadata,
                "UPDATE fundamental.artifact_references SET status='invalidated' "
                "WHERE artifact_id=:id",
                {"id": record.artifact_id},
            )
            readonly.require_current_records(
                ((record.artifact_id, record),), check_deadline=lambda: None
            )
    assert changed.value.code == "ARTIFACT_EVIDENCE_CHANGED"


def _bounded_artifact_read(store, identity, maximum_bytes, checked):
    if checked:
        return store.read_bounded_checked(
            identity, before=lambda record: maximum_bytes
        )[1]
    return store.read_bounded(identity, maximum_bytes=maximum_bytes)


@pytest.mark.parametrize("checked", (False, True))
def test_bounded_artifact_rechecks_actual_bytes_and_never_repairs_registration(
    metadata: PostgresMetadataStore, tmp_path: Path, checked: bool
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    raw = canonical_bytes({"retained": uuid4().hex})
    record = artifacts.put_bytes_with_receipt(uuid4().hex, raw).artifact
    readonly = artifacts.as_read_only()
    for store in (artifacts, readonly):
        assert (
            _bounded_artifact_read(store, record.artifact_id, len(raw), checked) == raw
        )
        with pytest.raises(SnapshotError) as overflow:
            _bounded_artifact_read(store, record.artifact_id, len(raw) - 1, checked)
        assert overflow.value.code == "FISCAL_CLOSURE_LIMIT"
    path = content._filesystem._path(record.content_hash, record.media_type)
    path.write_bytes(b"x" * len(raw))
    with pytest.raises(SnapshotError) as corrupt:
        _bounded_artifact_read(readonly, record.artifact_id, len(raw), checked)
    assert corrupt.value.code == "SOURCE_HASH_MISMATCH"
    path.write_bytes(raw)
    _change_artifact_metadata(
        metadata,
        "DELETE FROM fundamental.content_objects "
        "WHERE content_hash=:hash AND media_type=:media",
        {"hash": record.content_hash, "media": record.media_type},
    )
    for store in (artifacts, readonly):
        with pytest.raises(SnapshotError) as missing:
            _bounded_artifact_read(store, record.artifact_id, len(raw), checked)
        assert missing.value.code == "CONTENT_REGISTRATION_UNAVAILABLE"
    with pytest.raises(SnapshotError) as still_missing:
        metadata.content_byte_length(record.content_hash, media_type=record.media_type)
    assert still_missing.value.code == "CONTENT_REGISTRATION_UNAVAILABLE"


@pytest.mark.parametrize("artifact_change", ("missing", "different-pair"))
@pytest.mark.parametrize("registration_missing", (False, True))
@pytest.mark.parametrize("checked", (False, True))
def test_bounded_artifact_after_observes_original_pair_even_if_artifact_changes(
    metadata: PostgresMetadataStore,
    tmp_path: Path,
    monkeypatch,
    artifact_change: str,
    registration_missing: bool,
    checked: bool,
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    raw = canonical_bytes({"before": uuid4().hex})
    record = artifacts.put_bytes_with_receipt(uuid4().hex, raw).artifact
    replacement = artifacts.put(uuid4().hex, {"after": uuid4().hex})
    read = content._filesystem.get_bounded

    def change_after_read(*args, **kwargs):
        payload = read(*args, **kwargs)

        async def change():
            async with metadata._runner._engine.begin() as connection:
                if registration_missing:
                    await connection.execute(
                        text(
                            "DELETE FROM fundamental.content_objects "
                            "WHERE content_hash=:hash AND media_type=:media"
                        ),
                        {"hash": record.content_hash, "media": record.media_type},
                    )
                if artifact_change == "missing":
                    await connection.execute(
                        text(
                            "DELETE FROM fundamental.artifact_references "
                            "WHERE artifact_id=:id"
                        ),
                        {"id": record.artifact_id},
                    )
                else:
                    await connection.execute(
                        text(
                            "UPDATE fundamental.artifact_references "
                            "SET content_hash=:hash, media_type=:media "
                            "WHERE artifact_id=:id"
                        ),
                        {
                            "id": record.artifact_id,
                            "hash": replacement.content_hash,
                            "media": replacement.media_type,
                        },
                    )

        metadata._runner.run(change())
        return payload

    monkeypatch.setattr(content._filesystem, "get_bounded", change_after_read)
    expected_type = (
        SnapshotError
        if registration_missing or artifact_change == "missing"
        else DataReleaseError
    )
    with pytest.raises(expected_type) as refused:
        _bounded_artifact_read(artifacts, record.artifact_id, len(raw), checked)
    assert refused.value.code == (
        "CONTENT_REGISTRATION_UNAVAILABLE"
        if registration_missing
        else (
            "ARTIFACT_NOT_FOUND"
            if artifact_change == "missing"
            else "ARTIFACT_EVIDENCE_CHANGED"
        )
    )


@pytest.mark.parametrize("limits", ({}, {"max_entries": 0}, {"max_bytes": 1}))
@pytest.mark.parametrize("present", (False, True))
def test_checked_retained_reads_keep_absence_and_final_fresh_guard(
    metadata: PostgresMetadataStore, tmp_path: Path, limits, present
):
    from threading import get_ident

    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    identity = uuid4().hex
    raw = b'{"retained":true}'
    record = (
        artifacts.put_bytes_with_receipt(identity, raw).artifact if present else None
    )
    caller_thread = get_ident()
    observed = []

    def before(current):
        assert get_ident() == caller_thread
        observed.append(current)
        return len(raw)

    with pytest.raises(DataReleaseError) as changed:
        with artifacts.retained_read_operation((identity,), **limits) as reader:
            if present:
                assert reader.read_bounded_checked(identity, before=before) == (
                    record,
                    raw,
                )
                _change_artifact_metadata(
                    metadata,
                    "UPDATE fundamental.artifact_references SET status='invalidated' "
                    "WHERE artifact_id=:id",
                    {"id": identity},
                )
            else:
                with pytest.raises(SnapshotError) as missing:
                    reader.read_bounded_checked(identity, before=before)
                assert missing.value.code == "ARTIFACT_NOT_FOUND"
                artifacts.put_bytes_with_receipt(identity, raw)
    assert changed.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    assert observed == [record]
    with pytest.raises(RuntimeError, match="ended"):
        reader.read_bounded_checked(identity, before=before)
    assert observed == [record]


def test_retained_metadata_preserves_first_byte_failure_before_later_bad_row(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    first = artifacts.put(uuid4().hex, {"first": uuid4().hex})
    later = artifacts.put(uuid4().hex, {"later": uuid4().hex})
    _change_artifact_metadata(
        metadata,
        "UPDATE fundamental.artifact_references "
        "SET dependency_hashes=CAST(:dependencies AS jsonb) WHERE artifact_id=:id",
        {"id": later.artifact_id, "dependencies": json.dumps({"malformed": True})},
    )
    content._filesystem._path(first.content_hash, first.media_type).write_bytes(
        b"corrupt"
    )
    with pytest.raises(SnapshotError) as error:
        with artifacts.retained_read_operation(
            (first.artifact_id, later.artifact_id)
        ) as reader:
            reader.read(first.artifact_id)
            reader.get(later.artifact_id)
    assert error.value.code == "SOURCE_HASH_MISMATCH"
    with pytest.raises(ValueError):
        with artifacts.retained_read_operation((later.artifact_id,)) as reader:
            reader.get(later.artifact_id)


@pytest.mark.parametrize("fault", (None, "corrupt", "revoked"))
def test_retained_reads_repair_only_verified_content_registration(
    metadata: PostgresMetadataStore, tmp_path: Path, monkeypatch, fault: str | None
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    record = artifacts.put(uuid4().hex, {"repair": uuid4().hex})
    raw = artifacts.read(record.artifact_id)
    _change_artifact_metadata(
        metadata,
        "DELETE FROM fundamental.content_objects "
        "WHERE content_hash=:hash AND media_type=:media",
        {"hash": record.content_hash, "media": record.media_type},
    )
    if fault == "corrupt":
        content._filesystem._path(record.content_hash, record.media_type).write_bytes(
            b"corrupt"
        )
    if fault == "revoked":
        register = metadata.register_content

        def revoke(*args, **kwargs):
            register(*args, **kwargs)
            _change_artifact_metadata(
                metadata,
                "UPDATE fundamental.artifact_references "
                "SET status='invalidated' WHERE artifact_id=:id",
                {"id": record.artifact_id},
            )

        monkeypatch.setattr(metadata, "register_content", revoke)

    def read():
        with artifacts.retained_read_operation((record.artifact_id,)) as reader:
            assert reader.read(record.artifact_id) == raw
            assert reader.get(record.artifact_id) == record

    if fault is None:
        read()
    else:
        with pytest.raises(
            SnapshotError if fault == "corrupt" else DataReleaseError
        ) as error:
            read()
        assert error.value.code == (
            "SOURCE_HASH_MISMATCH"
            if fault == "corrupt"
            else "ARTIFACT_EVIDENCE_CHANGED"
        )
    assert metadata.has_content_hash(record.content_hash) is (fault != "corrupt")


@pytest.mark.parametrize("change_sibling", (False, True))
def test_registration_repair_covers_shared_content_without_accepting_other_changes(
    metadata: PostgresMetadataStore, tmp_path: Path, monkeypatch, change_sibling: bool
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    payload = {"shared": uuid4().hex}
    first = artifacts.put(uuid4().hex, payload)
    sibling = artifacts.put(uuid4().hex, payload)
    raw = artifacts.read(first.artifact_id)
    _change_artifact_metadata(
        metadata,
        "DELETE FROM fundamental.content_objects "
        "WHERE content_hash=:hash AND media_type=:media",
        {"hash": first.content_hash, "media": first.media_type},
    )
    register = metadata.register_content

    def repair(*args, **kwargs):
        register(*args, **kwargs)
        if change_sibling:
            _change_artifact_metadata(
                metadata,
                "UPDATE fundamental.artifact_references "
                "SET status='invalidated' WHERE artifact_id=:id",
                {"id": sibling.artifact_id},
            )

    monkeypatch.setattr(metadata, "register_content", repair)

    def read():
        with artifacts.retained_read_operation(
            (first.artifact_id, sibling.artifact_id)
        ) as reader:
            assert reader.read(first.artifact_id) == raw

    if change_sibling:
        with pytest.raises(DataReleaseError) as error:
            read()
        assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    else:
        read()


@pytest.mark.parametrize("limits", ({"max_entries": 0}, {"max_bytes": 1}))
def test_retained_metadata_initial_overflow_uses_current_base_reads(
    metadata: PostgresMetadataStore, tmp_path: Path, limits
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    record = artifacts.put(uuid4().hex, {"overflow": uuid4().hex})
    expected = artifacts.read(record.artifact_id)
    with pytest.raises(DataReleaseError) as error:
        with artifacts.retained_read_operation(
            (record.artifact_id,), **limits
        ) as reader:
            assert reader.read(record.artifact_id) == expected
            assert not reader._ids and not reader._records
            _change_artifact_metadata(
                metadata,
                "UPDATE fundamental.artifact_references "
                "SET status='invalidated' WHERE artifact_id=:id",
                {"id": record.artifact_id},
            )
            assert reader.get(record.artifact_id).status == "invalidated"
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    with pytest.raises(RuntimeError, match="ended"):
        reader.read(record.artifact_id)


@pytest.mark.parametrize("limit", ("entries", "bytes"))
@pytest.mark.parametrize("changed", (False, True))
def test_retained_metadata_indirect_overflow_checks_prior_records(
    metadata: PostgresMetadataStore, tmp_path: Path, limit: str, changed: bool
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    first = artifacts.put(uuid4().hex, {"first": uuid4().hex})
    indirect = artifacts.put(
        uuid4().hex,
        {"indirect": uuid4().hex},
        dependency_hashes=tuple(f"{index:064x}" for index in range(40)),
    )
    limits = {"max_entries": 1} if limit == "entries" else {"max_bytes": 2048}

    def read():
        with artifacts.retained_read_operation(
            (first.artifact_id,), **limits
        ) as reader:
            assert reader.get(first.artifact_id) == first
            assert not reader._fallback
            if changed:
                _change_artifact_metadata(
                    metadata,
                    "UPDATE fundamental.artifact_references "
                    "SET status='invalidated' WHERE artifact_id=:id",
                    {"id": first.artifact_id},
                )
            assert reader.read(indirect.artifact_id) == artifacts.read(
                indirect.artifact_id
            )
            assert not reader._ids and not reader._records
            assert reader.get(first.artifact_id) == first

    if changed:
        with pytest.raises(DataReleaseError) as error:
            read()
        assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    else:
        read()


@pytest.mark.parametrize("initial", (False, True))
@pytest.mark.parametrize(
    "fault", ("status", "dependency", "retention", "length", "missing")
)
def test_retained_metadata_overflow_keeps_the_final_guard(
    metadata: PostgresMetadataStore, tmp_path: Path, initial: bool, fault: str
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    first = artifacts.put(uuid4().hex, {"first": uuid4().hex})
    second = artifacts.put(uuid4().hex, {"second": uuid4().hex})
    ids = (first.artifact_id, second.artifact_id) if initial else (first.artifact_id,)
    with pytest.raises(DataReleaseError) as error:
        with artifacts.retained_read_operation(ids, max_entries=1) as reader:
            reader.read(first.artifact_id)
            reader.read(second.artifact_id)
            assert reader._fallback and not reader._ids and not reader._records
            journal = getattr(reader, "_journal", None)
            if fault == "missing":
                query = (
                    "DELETE FROM fundamental.artifact_references WHERE artifact_id=:id"
                )
            elif fault == "length":
                query = (
                    "UPDATE fundamental.content_objects SET byte_length=byte_length+1 "
                    "WHERE content_hash=:hash"
                )
            else:
                assignment = {
                    "status": "status='invalidated'",
                    "dependency": "dependency_hashes=CAST(:deps AS jsonb)",
                    "retention": "retention='operational_cache'",
                }[fault]
                query = f"UPDATE fundamental.artifact_references SET {assignment} WHERE artifact_id=:id"
            _change_artifact_metadata(
                metadata,
                query,
                {
                    "id": first.artifact_id,
                    "hash": first.content_hash,
                    "deps": json.dumps(["f" * 64]),
                },
            )
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    assert journal.closed and reader._journal is None
    with pytest.raises(RuntimeError, match="ended"):
        reader.get(first.artifact_id)


@pytest.mark.parametrize("revoke", (False, True))
def test_retained_metadata_spilled_alias_registration_repair(
    metadata: PostgresMetadataStore, tmp_path: Path, monkeypatch, revoke: bool
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    first = artifacts.put(uuid4().hex, {"shared": uuid4().hex})
    second = artifacts.put(uuid4().hex, json.loads(artifacts.read(first.artifact_id)))
    _change_artifact_metadata(
        metadata,
        "DELETE FROM fundamental.content_objects WHERE content_hash=:hash",
        {"hash": first.content_hash},
    )
    register = metadata.register_content

    def repair(*args, **kwargs):
        register(*args, **kwargs)
        if revoke:
            _change_artifact_metadata(
                metadata,
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:id",
                {"id": second.artifact_id},
            )

    monkeypatch.setattr(metadata, "register_content", repair)

    def read():
        with artifacts.retained_read_operation(
            (first.artifact_id, second.artifact_id, first.artifact_id), max_entries=1
        ) as reader:
            assert reader.read(first.artifact_id)
            assert reader.get(second.artifact_id) == second
            assert not reader._ids and not reader._records

    if revoke:
        with pytest.raises(DataReleaseError) as error:
            read()
        assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    else:
        read()


def test_retained_metadata_spilled_body_failure_closes_journal(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    record = artifacts.put(uuid4().hex, {"corrupt": uuid4().hex})
    content._filesystem._path(record.content_hash, record.media_type).write_bytes(
        b"bad"
    )
    with pytest.raises(SnapshotError):
        with artifacts.retained_read_operation(
            (record.artifact_id,), max_entries=0
        ) as reader:
            journal = reader._journal
            reader.read(record.artifact_id)
    assert journal.closed and reader._journal is None


def test_retained_metadata_spill_enrolls_the_complete_initial_set(
    metadata: PostgresMetadataStore, tmp_path: Path, monkeypatch
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    records = tuple(
        artifacts.put(uuid4().hex, {"entry": uuid4().hex}) for _ in range(12)
    )
    calls = []
    query = metadata._retained_artifact_records

    async def checked(ids, connection=None):
        if connection is not None:
            isolation = await connection.execute(text("SHOW transaction_isolation"))
            readonly = await connection.execute(text("SHOW transaction_read_only"))
            if readonly.scalar_one() == "on":
                calls.append((id(connection), isolation.scalar_one(), "on"))
        return await query(ids, connection)

    monkeypatch.setattr(metadata, "_retained_artifact_records", checked)
    ids = tuple(record.artifact_id for record in records)
    with artifacts.retained_read_operation(ids + ids, max_entries=2) as reader:
        reader.read(ids[0])
        assert not reader._ids and not reader._records
    assert len(calls) == 25
    assert len({call[0] for call in calls}) == 1
    assert all(call[1:] == ("repeatable read", "on") for call in calls)
    with pytest.raises(DataReleaseError) as error:
        with artifacts.retained_read_operation(ids, max_entries=2):
            _change_artifact_metadata(
                metadata,
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:id",
                {"id": ids[-1]},
            )
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"


def test_retained_metadata_spill_io_failure_cannot_return_success(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    record = artifacts.put(uuid4().hex, {"io": uuid4().hex})
    with pytest.raises(DataReleaseError) as error:
        with artifacts.retained_read_operation(
            (record.artifact_id,), max_entries=0
        ) as reader:
            reader.read(record.artifact_id)
            reader._journal.close()
    assert error.value.code == "DATA_RELEASE_ARTIFACT_UNAVAILABLE"
    assert reader._closed and reader._journal is None


def test_mapping_replay_batches_each_read_but_rechecks_before_return(
    metadata: PostgresMetadataStore, tmp_path: Path, monkeypatch
):
    from fundamental_service import automatic_mapping
    from fundamental_service.automatic_mapping import AutomaticMappingDecisionV1
    from fundamental_service.automatic_mapping_evidence import (
        AutomaticMappingEvidenceChecks,
    )
    from fundamental_service.data_releases import AutomaticMappingApprovalV1
    from test_automatic_mapping import approve, case

    request, source, roots, _ = case(
        tmp_path / "source", observation_changes={"context_id": uuid4().hex}
    )
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    prefix = uuid4().hex
    refs = []
    for ref in request.evidence_refs:
        identity = prefix + ref.artifact_id
        artifacts.put_bytes_with_receipt(
            identity, source.read(ref.artifact_id), media_type=ref.media_type
        )
        refs.append(ref.model_copy(update={"artifact_id": identity}))
    request = request.model_copy(update={"evidence_refs": tuple(refs)})
    receipt = approve(request, artifacts, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        artifacts.read(receipt.decision_publication.artifact.artifact_id)
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        artifacts.read(receipt.approval_publication.artifact.artifact_id)
    )
    batches = []
    fetch = metadata.retained_artifact_records

    def observed(ids):
        batches.append(ids)
        return fetch(ids)

    monkeypatch.setattr(metadata, "retained_artifact_records", observed)
    checks = AutomaticMappingEvidenceChecks()
    for _ in range(3):
        assert (
            automatic_mapping.verify_automatic_mapping_replay(
                approval, decision.mapping, artifacts=artifacts, evidence_checks=checks
            )
            == request
        )
    assert 6 <= len(batches) <= 12
    assert len({ids for ids in batches}) <= 3
    evaluate = automatic_mapping.evaluate_automatic_mapping

    def withdraw(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        _change_artifact_metadata(
            metadata,
            "UPDATE fundamental.artifact_references "
            "SET status='invalidated' WHERE artifact_id=:id",
            {"id": refs[0].artifact_id},
        )
        return result

    monkeypatch.setattr(automatic_mapping, "evaluate_automatic_mapping", withdraw)
    with pytest.raises(DataReleaseError) as error:
        automatic_mapping.verify_automatic_mapping_replay(
            approval, decision.mapping, artifacts=artifacts, evidence_checks=checks
        )
    assert error.value.code == "ARTIFACT_EVIDENCE_CHANGED"


def test_distinct_sec_acquisition_keys_hold_independent_postgres_locks(
    metadata: PostgresMetadataStore,
):
    first = metadata.try_acquire_ingestion_lock(sha256_digest({"key": "first"}))
    second = metadata.try_acquire_ingestion_lock(sha256_digest({"key": "second"}))

    try:
        assert first is not None
        assert second is not None
    finally:
        if second is not None:
            metadata.release_ingestion_lock(second)
        if first is not None:
            metadata.release_ingestion_lock(first)


def test_terminated_ingestion_owner_releases_postgres_single_flight_lock(
    metadata: PostgresMetadataStore,
):
    assert DATABASE_URL is not None
    acquisition_key = sha256_digest({"issue": 312, "process-crash": uuid4().hex})
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_ingestion_lock_until_terminated,
        args=(DATABASE_URL, acquisition_key, acquired, release),
    )
    process.start()
    try:
        assert acquired.wait(timeout=20)
        assert process.is_alive()
        assert metadata.try_acquire_ingestion_lock(acquisition_key) is None
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        assert process.exitcode is not None and process.exitcode != 0

        recovered_lease = metadata.try_acquire_ingestion_lock(acquisition_key)
        assert recovered_lease is not None
        metadata.release_ingestion_lock(recovered_lease)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)


def test_sec_ingestion_publish_rolls_back_snapshot_and_facts_then_recovers(
    metadata: PostgresMetadataStore,
    monkeypatch: pytest.MonkeyPatch,
):
    run_id = uuid4().hex
    acquisition_key = sha256_digest({"issue": 312, "run_id": run_id})
    acquisition_payload = {"run_id": run_id, "selector": "same-request"}
    snapshot = _snapshot(
        run_id,
        acquisition_key=acquisition_key,
        taxonomy_manifest_id="taxonomy-test-v1",
        validation_profile_id="sec-efm-us-dqc-v31.0.3",
        validation_profile_digest="b" * 64,
        parser_version="2.47.4",
    )
    fact = _fact_for_snapshot(snapshot, f"fact-{run_id}")
    result = _sec_ingestion_result(
        snapshot,
        correlation_id=f"correlation-{run_id}",
        canonical_fact_ids=(fact.fact_id,),
    )
    original_payload_json = metadata._payload_json

    def fail_before_acquisition_insert(payload: object) -> str:
        if payload == acquisition_payload:
            raise RuntimeError("injected metadata publication failure")
        return original_payload_json(payload)

    monkeypatch.setattr(metadata, "_payload_json", fail_before_acquisition_insert)
    with pytest.raises(RuntimeError, match="injected metadata publication failure"):
        metadata.publish_sec_ingestion(
            acquisition_key=acquisition_key,
            acquisition_payload=acquisition_payload,
            snapshot=snapshot,
            facts=(fact,),
            result=result,
            caller_principal="caller-1",
            organization_id="org-1",
        )

    assert metadata.get_sec_ingestion(acquisition_key) is None
    with pytest.raises(SnapshotError):
        metadata.get_snapshot(snapshot.snapshot_id)
    with pytest.raises(SnapshotError):
        metadata.get_fact(fact.fact_id)

    monkeypatch.setattr(metadata, "_payload_json", original_payload_json)
    published = metadata.publish_sec_ingestion(
        acquisition_key=acquisition_key,
        acquisition_payload=acquisition_payload,
        snapshot=snapshot,
        facts=(fact,),
        result=result,
        caller_principal="caller-1",
        organization_id="org-1",
    )
    assert published == result
    assert metadata.get_snapshot(snapshot.snapshot_id) == snapshot
    assert metadata.get_fact(fact.fact_id) == fact
    assert (
        metadata.get_sec_ingestion(
            acquisition_key, expected_acquisition_payload=acquisition_payload
        )
        == result
    )


@pytest.mark.parametrize("transactional", [False, True])
@pytest.mark.parametrize("mutation", ["value", "source"])
def test_fact_publication_reuses_source_identity_across_selection_views(
    metadata, transactional, mutation
):
    suffix = uuid4().hex
    snapshot = _snapshot(suffix)
    fact = _fact_for_snapshot(snapshot, f"fact-{suffix}").model_copy(
        update={
            "point_in_time_policy": "sec-public-pit-v1",
            "selection_reason": "first PIT selection",
            "rejected_candidate_reasons": (
                CandidateRejectionV1(candidate_id="later", reason="not available"),
            ),
        }
    )
    metadata.publish_fact(fact)
    second_view = fact.model_copy(
        update={
            "selection_reason": "another valid PIT selection",
            "rejected_candidate_reasons": (),
        }
    )

    def publish(value):
        if transactional:
            result = _sec_ingestion_result(
                snapshot, correlation_id=suffix, canonical_fact_ids=(value.fact_id,)
            )
            metadata.publish_sec_ingestion(
                acquisition_key=sha256_digest({"fact": value.model_dump(mode="json")}),
                acquisition_payload={"suffix": suffix},
                snapshot=snapshot,
                facts=(value,),
                result=result,
                caller_principal="test-caller",
                organization_id="test-org",
            )
        else:
            metadata.publish_fact(value)

    publish(second_view)
    publish(second_view)
    assert metadata.get_fact(fact.fact_id) == fact
    assert canonical_fact_digest(fact) == canonical_fact_digest(second_view)
    with pytest.raises(SnapshotError) as error:
        publish(
            second_view.model_copy(
                update={"value": Decimal(101)}
                if mutation == "value"
                else {
                    "source": fact.source.model_copy(update={"content_hash": "e" * 64})
                }
            )
        )
    assert error.value.code == (
        "INGESTION_FACT_SOURCE_MISMATCH"
        if transactional and mutation == "source"
        else "METADATA_IMMUTABLE"
    )
    assert metadata.get_fact(fact.fact_id) == fact


def test_concurrent_fact_selection_views_publish_one_canonical_row(metadata):
    suffix = uuid4().hex
    fact = _fact_for_snapshot(_snapshot(suffix), f"fact-{suffix}")
    barrier = Barrier(2)

    def publish(reason):
        view = fact.model_copy(
            update={
                "selection_reason": reason,
                "point_in_time_policy": "sec-public-pit-v1",
            }
        )
        barrier.wait(timeout=5)
        metadata.publish_fact(view)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(publish, ("first view", "second view")))
    retained = metadata.get_fact(fact.fact_id)
    assert retained.selection_reason in {"first view", "second view"}
    assert canonical_fact_digest(retained) == canonical_fact_digest(fact)
    assert sum(value.fact_id == fact.fact_id for value in metadata.list_facts()) == 1


def test_unauthorized_sec_ingestion_is_rejected_and_audited_in_postgres(
    metadata: PostgresMetadataStore,
):
    request = _sec_ingestion_request()
    correlation_id = f"unauthorized-{uuid4().hex}"
    use_case = object.__new__(SecAcquisitionUseCase)
    use_case.metadata = metadata
    use_case.authorized_organizations = frozenset({"org-approved"})
    use_case.settings = _test_sec_acquisition_settings(request)
    app = create_app(
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
        sec_acquisition=use_case,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/data/ingestions",
            headers=auth_headers(organization_id="org-unapproved"),
            json=make_internal_envelope(
                request.model_dump(mode="json"),
                correlation_id=correlation_id,
                organization_id="org-unapproved",
            ),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INGESTION_NOT_AUTHORIZED"

    async def read_audit() -> tuple[str, str, str, tuple[str, ...], str]:
        async with metadata._runner._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT acquisition_key, caller_principal, organization_id, "
                        "source_hashes, outcome FROM "
                        "fundamental.source_acquisition_audits "
                        "WHERE correlation_id=:correlation_id"
                    ),
                    {"correlation_id": correlation_id},
                )
            ).one()
            return (
                str(row[0]).strip(),
                str(row[1]),
                str(row[2]),
                tuple(row[3]),
                str(row[4]),
            )

    audit = metadata._runner.run(read_audit())
    assert audit == (
        sha256_digest(_runtime_acquisition_payload(request, use_case.settings)),
        "subject-test",
        "org-unapproved",
        (),
        "INGESTION_NOT_AUTHORIZED",
    )


def test_fifty_sec_ingestion_contenders_across_processes_publish_once(
    metadata: PostgresMetadataStore,
):
    assert DATABASE_URL is not None
    run_id = uuid4().hex
    table = f"issue312_coalescing_{run_id}"
    request = _sec_ingestion_request().model_copy(
        update={"policy_version": f"sec-public-pit-{run_id}"}
    )
    acquisition_payload = _runtime_acquisition_payload(request)
    acquisition_key = sha256_digest(acquisition_payload)

    async def create_probe() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    f"CREATE TABLE fundamental.{table} ("
                    "run_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL, "
                    "provider_calls INTEGER NOT NULL)"
                )
            )
            await connection.execute(
                text(
                    f"INSERT INTO fundamental.{table} "
                    "(run_id, attempts, provider_calls) VALUES (:run_id, 0, 0)"
                ),
                {"run_id": run_id},
            )

    async def read_probe() -> tuple[int, int]:
        async with metadata._runner._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        f"SELECT attempts, provider_calls "
                        f"FROM fundamental.{table} WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).one()
            return int(row[0]), int(row[1])

    async def read_audit_outcomes() -> dict[str, int]:
        async with metadata._runner._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT outcome, count(*) FROM "
                        "fundamental.source_acquisition_audits "
                        "WHERE acquisition_key=:acquisition_key GROUP BY outcome"
                    ),
                    {"acquisition_key": acquisition_key},
                )
            ).all()
            return {str(row[0]): int(row[1]) for row in rows}

    async def drop_probe() -> None:
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE fundamental.{table}"))

    metadata._runner.run(create_probe())
    try:
        context = multiprocessing.get_context("spawn")
        with context.Manager() as manager:
            process_barrier = manager.Barrier(10)
            with ProcessPoolExecutor(max_workers=10, mp_context=context) as executor:
                groups = tuple(
                    executor.submit(
                        _cross_process_ingestion_contenders,
                        DATABASE_URL,
                        acquisition_key,
                        acquisition_payload,
                        table,
                        run_id,
                        process_barrier,
                        group_number,
                    )
                    for group_number in range(10)
                )
                outcomes = tuple(
                    result for group in groups for result in group.result(timeout=120)
                )

        assert len(outcomes) == 50
        first_outcomes = tuple(outcome[0] for outcome in outcomes)
        assert first_outcomes.count("published") == 1
        assert first_outcomes.count("ingestion_in_progress") == 49
        first_success_references = {
            (outcome[1], outcome[2])
            for outcome in outcomes
            if outcome[0] == "published"
        }
        assert len(first_success_references) == 1
        attempts, provider_calls = metadata._runner.run(read_probe())
        assert (attempts, provider_calls) == (50, 1)
        result = metadata.get_sec_ingestion(
            acquisition_key, expected_acquisition_payload=acquisition_payload
        )
        assert result is not None
        assert result.status == "degraded"
        assert metadata.get_snapshot(result.snapshot_id or "").manifest_digest == (
            result.manifest_digest
        )

        use_case = object.__new__(SecAcquisitionUseCase)
        use_case._original_reads = ContextVar(
            "original_preparation_reads", default=None
        )
        use_case.capture_store = None
        use_case.metadata = metadata
        use_case.authorized_organizations = frozenset({"org-sec-ingestion-test"})
        use_case.settings = _test_sec_acquisition_settings(request)
        app = create_app(
            config=OperationsConfig(
                service_token=TEST_SERVICE_TOKEN,
                rate_limit_per_minute=1_000,
                ingestion_rate_limit_per_minute=1_000,
            ),
            sec_acquisition=use_case,
        )
        with TestClient(app) as client:
            reused_references = set()
            for attempt in range(50):
                envelope = make_internal_envelope(
                    request.model_dump(mode="json"),
                    correlation_id=f"reuse-{run_id}-{attempt}",
                    organization_id="org-sec-ingestion-test",
                )
                response = client.post(
                    "/v1/data/ingestions",
                    headers=auth_headers(organization_id="org-sec-ingestion-test"),
                    json=envelope,
                )
                assert response.status_code == 200, response.text
                response_body = response.json()["result"]
                assert response_body["status"] == "reused"
                assert response_body["reused"] is True
                reused_references.add(
                    (response_body["snapshot_id"], response_body["manifest_digest"])
                )
        assert reused_references == first_success_references
        assert metadata._runner.run(read_audit_outcomes()) == {
            "INGESTION_IN_PROGRESS": 49,
            "degraded": 1,
            "reused": 50,
        }
    finally:
        metadata._runner.run(drop_probe())
