from __future__ import annotations

import multiprocessing
import os
import time
import base64
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
from fundamental_service.app import create_app
from fundamental_service.contracts import (
    CanonicalFactV1,
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
    DataReleaseVerifierV1,
    DataReleaseVerificationV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.metadata import (
    SCHEMA_VERSION,
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
)
from fundamental_service.operations import OperationsConfig
from fundamental_service.policies import PolicyRecordV1, initial_model_specs
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecRequestPolicy
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_acquisition import SecAcquisitionUseCase
from fundamental_service.testsupport import (
    TEST_SERVICE_TOKEN,
    auth_headers,
    make_internal_envelope,
    make_valuation,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

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
        edgar_plugin_dir=Path("/runtime/arelle/EDGAR"),
        xule_plugin_dir=Path("/runtime/arelle/Xule"),
        dqc_ruleset_path=Path("/runtime/arelle/dqc-ruleset.xml"),
        edgar_plugin_sha256="a" * 64,
        xule_plugin_sha256="b" * 64,
        dqc_ruleset_sha256="d" * 64,
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
        value=Decimal("100"),
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
    ) -> SecIngestionResponseV1:
        _ = deadline_at
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
        metadata.publish_sec_ingestion(
            acquisition_key=acquisition_key,
            acquisition_payload=key_payload,
            snapshot=snapshot,
            facts=(),
            result=result,
            caller_principal=caller_principal,
            organization_id=organization_id,
        )
        deadline = time.monotonic() + 30
        while (
            metadata._runner.run(_coalescing_probe_attempts(metadata, table, run_id))
            < 50
        ):
            if time.monotonic() >= deadline:
                raise TimeoutError("not all HTTP requests reached PostgreSQL")
            time.sleep(0.01)
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
    command = _activation_command(manifest)

    active = metadata.compare_and_swap_data_release(command)
    assert active.profile_id == manifest.profile_id
    assert active.manifest_digest == manifest.manifest_digest
    assert active.revision == 1
    resolved = metadata.get_active_data_release_with_manifest(manifest.profile_id)
    assert resolved is not None
    assert resolved.active == active
    assert resolved.manifest == manifest
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
        "policy_id": "policy-postgres-v1",
        "policy_version": "policy-postgres-v1",
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

    def publish() -> str:
        return artifacts.put(artifact_id, {"value": "immutable"}).content_hash

    with ThreadPoolExecutor(max_workers=6) as executor:
        hashes = tuple(executor.map(lambda _: publish(), range(12)))
    assert set(hashes) == {hashes[0]}
    assert artifacts.read(artifact_id) == b'{"value":"immutable"}'

    record = artifacts.get(artifact_id)
    path = content._filesystem._path(record.content_hash, record.media_type)
    path.write_bytes(b"tampered")
    with pytest.raises(SnapshotError, match="verification"):
        artifacts.read(artifact_id)


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
