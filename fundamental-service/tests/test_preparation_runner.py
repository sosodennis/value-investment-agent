import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from fundamental_service.app import create_app
from fundamental_service.contracts import (
    CallerApprovalEnvelopeV1,
    QualityStatus,
    SecIngestionResponseV1,
    SecMappingReferenceV1,
)
from fundamental_service.data_releases import (
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
    DataReleaseCandidatePublishRequestV1,
    DataReleaseError,
    DataReleaseManifestV1,
    MappingRefV1,
    verify_data_release_candidate,
    sign_data_release_verification,
    sign_mapping_review_evidence,
)
from fundamental_service.facts import (
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
)
from fundamental_service.operations import OperationsConfig, ServiceError
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresCanonicalFactRepository,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
)
from fundamental_service.preparation_runner import (
    SourcePreparationEvidenceV1,
    SourcePreparationPlanV2,
    SourcePreparationRunner,
    main,
)
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.replay import ArtifactRecordV1, ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_api import _release_manifest_for
from test_postgres_metadata import DATABASE_URL, _sec_ingestion_request, _snapshot
from test_release_runner import _candidate
from test_history_composition import _changed, _original
from test_valuation_preparation import _facts
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


REVISION = "1" * 40
VALUATION_TIME = datetime(2026, 3, 1, tzinfo=UTC)


def _fixture(tmp_path: Path, *, released: bool = True, namespace: str = "runner"):
    source_bytes = b'{"source":"synthetic original filing fixture"}'
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    required = valuation_requirements_profile("fcff_dcf").required_fact_fields
    base = _sec_ingestion_request()
    ingestion = base.model_copy(
        update={
            "identity": base.identity.model_copy(
                update={"security_id": f"COMMON-{namespace}"}
            ),
            "valuation_timestamp": VALUATION_TIME,
            "required_fields": required,
            "mappings": tuple(
                SecMappingReferenceV1(
                    decision_id=f"mapping-{field}",
                    mapping_version="mapping-v1",
                    normalized_field=field,
                )
                for field in required
            ),
        }
    )
    plan = SourcePreparationPlanV2(
        source_revision=REVISION,
        release_profile_id=f"sec-public-pit-{namespace}",
        model_id="fcff_dcf",
        ingestions=(ingestion,),
    )
    snapshot = _snapshot(
        namespace,
        identity=ingestion.identity,
        valuation_timestamp=VALUATION_TIME,
        parser_version=ingestion.parser_version,
        policy_version=ingestion.policy_version,
        taxonomy_manifest_id=ingestion.taxonomy_manifest_id,
        validation_profile_id=ingestion.validation_profile_id,
    )
    sources = tuple(
        source.model_copy(
            update={
                "accession_number": base.filing.accession_number,
                "content_hash": source_hash,
            }
        )
        for source in snapshot.source_records
    )
    payload = snapshot.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = sources
    payload["manifest_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "snapshot_id"}
    )
    snapshot = type(snapshot)(**payload)
    snapshots = FilesystemSnapshotRepository(tmp_path / "snapshots")
    snapshots.publish(snapshot)
    facts = FilesystemCanonicalFactRepository(tmp_path / "facts")
    mappings = {
        f"mapping-{field}": CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=f"mapping-{field}",
            source_concept=f"us-gaap:{field}",
            normalized_field=field,
            mapping_version="mapping-v1",
            confidence="high",
            status="approved",
            reviewer="contract-test-reviewer",
        )
        for field in required
    }
    stored = tuple(
        fact.model_copy(
            update={
                "issuer_id": ingestion.identity.issuer_id,
                "security_id": ingestion.identity.security_id,
                "fact_id": f"{fact.fact_id}:{namespace}",
                "mapping_decision_id": f"mapping-{fact.normalized_field}",
                "mapping_confidence": "high",
                "captured_at": VALUATION_TIME,
                "source": fact.source.model_copy(update={"content_hash": source_hash}),
            }
        )
        for fact in _facts()
    )
    for fact in stored:
        facts.publish(fact)
    manifest = _release_manifest_for(snapshot, stored)
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        profile_id=plan.release_profile_id,
        required_fields=required,
        mapping_refs=tuple(
            MappingRefV1(mapping_id=key, mapping_digest=sha256_digest(mapping))
            for key, mapping in sorted(mappings.items())
        ),
    )
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    active = ActiveDataReleaseWithManifestV1(
        active=ActiveDataReleaseV1(
            profile_id=manifest.profile_id,
            manifest_digest=manifest.manifest_digest,
            revision=1,
            activated_at=VALUATION_TIME,
        ),
        manifest=manifest,
    )
    state = SimpleNamespace(active=active if released else None, publications=0)
    metadata = SimpleNamespace(
        get_active_data_release_with_manifest=lambda profile: state.active,
        get_data_release_manifest=lambda digest: (
            manifest if digest == manifest.manifest_digest else None
        ),
        get_mapping=mappings.__getitem__,
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    config = replace(
        OperationsConfig.testing(),
        release_publish_authorized_organizations=frozenset({"operators"}),
        release_activation_authorized_organizations=frozenset({"operators"}),
    )
    application = create_app(
        snapshot_repository=snapshots,
        fact_repository=facts,
        artifact_store=artifacts,
        metadata_store=metadata,
        config=config,
    ).state.application
    return SimpleNamespace(
        plan=plan,
        snapshot=snapshot,
        snapshots=snapshots,
        application=application,
        metadata=metadata,
        manifest=manifest,
        mappings=mappings,
        facts=facts,
        artifacts=artifacts,
        active=active,
        state=state,
        source_bytes=source_bytes,
    )


def _run(runner, plan, *, correlation="first", **kwargs):
    return runner.run(
        plan,
        actor_id="operator",
        organization_id="operators",
        correlation_id=correlation,
        deadline_at=datetime.now(UTC) + timedelta(minutes=2),
        **kwargs,
    )


def _reader(fixture, receipt):
    return SourcePreparationEvidenceV1.model_validate_json(
        fixture.artifacts.read(receipt.artifact.artifact_id)
    )


def _runner(fixture, *, acquisition=None, canary=None):
    return SourcePreparationRunner(
        application=fixture.application,
        acquisition=acquisition,
        artifacts=fixture.artifacts,
        canary=canary,
    )


def _acquisition(fixture, *, quality=QualityStatus.VERIFIED):
    calls = []

    def execute(request, **kwargs):
        calls.append(request)
        fixture.snapshots.publish(fixture.snapshot)
        return SecIngestionResponseV1(
            contract_version="fundamental.v1",
            status="created" if quality is QualityStatus.VERIFIED else "degraded",
            identity=request.identity,
            valuation_timestamp=request.valuation_timestamp,
            snapshot_id=fixture.snapshot.snapshot_id,
            manifest_digest=fixture.snapshot.manifest_digest,
            quality_status=quality,
            issue_codes=()
            if quality is QualityStatus.VERIFIED
            else ("MAPPING_MISSING",),
            missing_evidence=() if quality is QualityStatus.VERIFIED else ("revenue",),
            parser_version=request.parser_version,
            validation_profile_id=request.validation_profile_id,
            validation_profile_digest="a" * 64,
            taxonomy_manifest_id=request.taxonomy_manifest_id,
            taxonomy_version=request.taxonomy_version,
            correlation_id=kwargs["correlation_id"],
        )

    return SimpleNamespace(execute=execute, calls=calls)


def _reviewed_candidate(fixture):
    seed_manifest, verification, _, _, _, artifacts, roots = _candidate()
    manifest_payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    manifest_payload.update(
        taxonomy_refs=seed_manifest.taxonomy_refs,
        artifact_refs=seed_manifest.artifact_refs,
    )
    manifest = DataReleaseManifestV1(
        **manifest_payload, manifest_digest=sha256_digest(manifest_payload)
    )
    verification_payload = verification.model_dump(
        exclude={"signature", "verification_digest"}
    )
    review_payload = verification.mapping_reviews[0].model_dump(exclude={"signature"})
    verification_payload.update(
        manifest_digest=manifest.manifest_digest,
        mapping_reviews=tuple(
            sign_mapping_review_evidence(
                {
                    **review_payload,
                    "mapping_id": reference.mapping_id,
                    "mapping_digest": reference.mapping_digest,
                },
                Ed25519PrivateKey.from_private_bytes(b"reviewer-key".ljust(32, b"0")),
            )
            for reference in manifest.mapping_refs
        ),
    )
    verification = sign_data_release_verification(
        verification_payload,
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    candidate = DataReleaseCandidatePublishRequestV1(
        manifest=manifest, verification=verification
    )

    def publish(manifest, verification):
        verify_data_release_candidate(manifest, verification, roots)
        fixture.state.publications += 1

    def activate(command):
        active = fixture.state.active
        if command.expected_revision != (
            0 if active is None else active.active.revision
        ):
            raise DataReleaseError("DATA_RELEASE_POINTER_CONFLICT", "changed")
        fixture.state.active = ActiveDataReleaseWithManifestV1(
            active=ActiveDataReleaseV1(
                profile_id=manifest.profile_id,
                manifest_digest=manifest.manifest_digest,
                revision=1,
                activated_at=VALUATION_TIME,
            ),
            manifest=manifest,
        )
        return fixture.state.active.active

    fixture.metadata.publish_data_release_candidate = publish
    fixture.metadata.compare_and_swap_data_release = activate
    fixture.metadata.get_data_release_manifest = lambda digest: (
        manifest if digest == manifest.manifest_digest else None
    )
    canary = DataReleaseCanaryRunner(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        mapping_reader=fixture.metadata,
        artifact_reader=artifacts,
        trust_roots=roots,
    )
    return candidate, canary


def test_released_source_uses_formal_composer_and_reuses_artifact_after_restart(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    runner = _runner(fixture)

    first = _run(runner, fixture.plan)
    prepared = _reader(fixture, first)
    repeated = _run(runner, fixture.plan, correlation="second")
    restarted = SourcePreparationRunner(
        application=fixture.application,
        acquisition=None,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        canary=None,
    )
    after_restart = _run(restarted, fixture.plan)

    assert prepared.status == "approval_required"
    assert prepared.preparation.status == "prepared"
    assert prepared.preparation.quality_status is QualityStatus.PROVISIONAL
    assert "HISTORY_THRESHOLD_UNVALIDATED" in prepared.preparation.issue_codes
    assert first.wrote is True
    assert repeated.wrote is False
    assert after_restart.wrote is False
    assert first.artifact == repeated.artifact == after_restart.artifact
    assert fixture.snapshot.manifest_digest in first.artifact.dependency_hashes


def test_source_miss_retains_unreleased_snapshot_without_self_approval(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    acquisition = _acquisition(fixture)
    runner = _runner(fixture, acquisition=acquisition)

    first = _run(runner, fixture.plan)
    repeated = _run(runner, fixture.plan, correlation="another")
    evidence = _reader(fixture, first)

    assert evidence.status == "release_required"
    assert evidence.snapshot_id == fixture.snapshot.snapshot_id
    assert evidence.preparation is None
    assert repeated.artifact == first.artifact
    assert repeated.wrote is False
    assert len(acquisition.calls) == 2
    assert fixture.state.active is None


def test_reviewed_candidate_resumes_acquisition_into_formal_preparation(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    (tmp_path / "snapshots" / f"{fixture.snapshot.snapshot_id}.json").unlink()
    acquisition = _acquisition(fixture)
    candidate, canary = _reviewed_candidate(fixture)
    runner = _runner(fixture, acquisition=acquisition, canary=canary)

    first = _run(runner, fixture.plan, candidate=candidate)
    repeated = _run(runner, fixture.plan)
    evidence = _reader(fixture, first)

    assert evidence.status == "approval_required"
    assert evidence.data_release_manifest_digest == candidate.manifest.manifest_digest
    assert len(acquisition.calls) == 1
    assert fixture.state.publications == 1
    assert repeated.wrote is False
    assert first.artifact == repeated.artifact


def test_reviewed_candidate_reuses_retained_snapshot_before_activation(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    candidate, canary = _reviewed_candidate(fixture)
    runner = _runner(fixture, canary=canary)

    first = _run(runner, fixture.plan, candidate=candidate)
    repeated = _run(runner, fixture.plan)

    assert _reader(fixture, first).status == "approval_required"
    assert fixture.state.publications == 1
    assert repeated.wrote is False
    assert repeated.artifact == first.artifact


def test_untrusted_candidate_cannot_publish_or_activate(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    candidate, canary = _reviewed_candidate(fixture)
    candidate = candidate.model_copy(
        update={
            "verification": candidate.verification.model_copy(
                update={"signature": "0" * 128}
            )
        }
    )
    runner = _runner(fixture, acquisition=_acquisition(fixture), canary=canary)

    with pytest.raises(DataReleaseError):
        _run(runner, fixture.plan, candidate=candidate)
    assert fixture.state.active is None
    assert fixture.state.publications == 0


def test_acquisition_failure_is_retained_as_blocked(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    runner = _runner(
        fixture, acquisition=_acquisition(fixture, quality=QualityStatus.ABSTAIN)
    )

    first = _run(runner, fixture.plan)
    repeated = _run(runner, fixture.plan)
    evidence = _reader(fixture, first)

    assert evidence.status == "blocked"
    assert evidence.issue_codes == ("MAPPING_MISSING",)
    assert evidence.missing_evidence == ("revenue",)
    assert repeated.wrote is False


def test_corrupt_release_does_not_trigger_provider_io(tmp_path):
    fixture = _fixture(tmp_path)
    acquisition = _acquisition(fixture)

    def corrupt(_):
        raise ServiceError(
            "DATA_RELEASE_MAPPING_MISMATCH", "corrupt", status_code=409, retryable=False
        )

    fixture.metadata.get_active_data_release_with_manifest = corrupt
    with pytest.raises(ServiceError, match="corrupt"):
        _run(_runner(fixture, acquisition=acquisition), fixture.plan)
    assert acquisition.calls == []


@pytest.mark.parametrize(
    "code", ["REQUIRED_FACTS_UNAVAILABLE", "EFM_VALIDATION_FAILED"]
)
def test_rejected_acquisition_retains_stable_failure_without_snapshot(tmp_path, code):
    fixture = _fixture(tmp_path, released=False)

    def execute(*args, **kwargs):
        raise ServiceError(code, "rejected source", status_code=422, retryable=False)

    runner = _runner(fixture, acquisition=SimpleNamespace(execute=execute))
    first = _run(runner, fixture.plan)
    repeated = _run(runner, fixture.plan, correlation="another")
    evidence = _reader(fixture, first)
    assert evidence.status == "blocked"
    assert evidence.issue_codes == (code,)
    assert evidence.snapshot_id is None
    assert first.wrote is True
    assert repeated.wrote is False
    assert repeated.artifact == first.artifact


@pytest.mark.parametrize("status,retryable", [(403, False), (409, True), (503, True)])
def test_denial_or_transient_acquisition_does_not_publish_evidence(
    tmp_path, status, retryable
):
    fixture = _fixture(tmp_path, released=False)

    def execute(*args, **kwargs):
        raise ServiceError(
            "UNAVAILABLE", "unavailable", status_code=status, retryable=retryable
        )

    runner = _runner(fixture, acquisition=SimpleNamespace(execute=execute))
    before = tuple((tmp_path / "artifacts").rglob("*.json"))
    with pytest.raises(ServiceError):
        _run(runner, fixture.plan)
    assert tuple((tmp_path / "artifacts").rglob("*.json")) == before


def test_approval_is_bound_to_prepared_input_and_rejection_never_calculates(tmp_path):
    fixture = _fixture(tmp_path)
    runner = _runner(fixture)
    preparation = _reader(fixture, _run(runner, fixture.plan)).preparation
    approval = CallerApprovalEnvelopeV1(
        input_digest=preparation.input.input_digest,
        decision="rejected",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    rejected = _reader(fixture, _run(runner, fixture.plan, approval=approval))
    assert rejected.status == "blocked"
    assert rejected.issue_codes == ("CALLER_APPROVAL_REJECTED",)
    assert rejected.calculation is None
    with pytest.raises(ValueError, match="different valuation input"):
        _run(
            runner,
            fixture.plan,
            approval=approval.model_copy(update={"input_digest": "f" * 64}),
        )
    with pytest.raises(ValueError, match="identity"):
        _run(
            runner,
            fixture.plan,
            approval=approval.model_copy(update={"caller_id": "other"}),
        )


def test_approved_preparation_calculates_and_repeat_is_unchanged(tmp_path):
    fixture = _fixture(tmp_path)
    runner = _runner(fixture)
    preparation = _reader(fixture, _run(runner, fixture.plan)).preparation
    approval = CallerApprovalEnvelopeV1(
        input_digest=preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )

    first = _run(runner, fixture.plan, approval=approval)
    repeated = _run(runner, fixture.plan, correlation="different", approval=approval)
    evidence = _reader(fixture, first)

    assert evidence.status == "calculated"
    assert evidence.calculation.base.per_share_value > 0
    assert evidence.calculation.base.quality_status is QualityStatus.PROVISIONAL
    assert evidence.calculation.artifact_references
    assert first.artifact == repeated.artifact
    assert first.wrote is True
    assert repeated.wrote is False


def test_concurrent_preparations_publish_one_artifact(tmp_path):
    fixture = _fixture(tmp_path)

    def prepare(_):
        return _run(_runner(fixture), fixture.plan)

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = tuple(executor.map(prepare, range(8)))
    assert sum(receipt.wrote for receipt in receipts) == 1
    assert len({receipt.artifact.content_hash for receipt in receipts}) == 1


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL is required")
def test_preparation_and_calculation_reuse_postgres_artifacts_after_restart_and_restore(
    tmp_path, recovery_databases
):
    source_database, target_database = recovery_databases
    fixture = _fixture(tmp_path, released=False, namespace=uuid4().hex)
    candidate, _ = _reviewed_candidate(fixture)
    _, _, _, _, _, review_artifacts, roots = _candidate()
    store = PostgresMetadataStore(
        source_database, auto_migrate=True, data_release_trust_roots=roots
    )
    store.start()

    def wire(metadata, content_root=None):
        content = PostgresContentStore(
            content_root or tmp_path / "durable-content", metadata
        )
        artifacts = PostgresArtifactStore(metadata, content)
        application = create_app(
            snapshot_repository=PostgresSnapshotRepository(metadata),
            fact_repository=PostgresCanonicalFactRepository(metadata),
            content_store=content,
            artifact_store=artifacts,
            metadata_store=metadata,
            config=fixture.application.config,
        ).state.application
        runner = SourcePreparationRunner(
            application=application,
            acquisition=None,
            artifacts=artifacts,
            canary=DataReleaseCanaryRunner(
                snapshot_repository=application.snapshot_repository,
                fact_repository=application.fact_repository,
                mapping_reader=metadata,
                artifact_reader=artifacts,
                trust_roots=roots,
            ),
        )
        return runner, content, artifacts

    def content_inventory():
        return tuple(
            (
                path.relative_to(tmp_path).as_posix(),
                path.stat().st_mtime_ns,
                path.read_bytes(),
            )
            for path in sorted((tmp_path / "durable-content").rglob("*"))
            if path.is_file()
        )

    try:
        runner, content, artifacts = wire(store)
        content.put(fixture.source_bytes, media_type="application/json")
        store.publish_snapshot(fixture.snapshot)
        for fact in fixture.facts.list():
            store.publish_fact(fact)
        for mapping in fixture.mappings.values():
            store.publish_mapping(mapping)
        for reference in candidate.manifest.artifact_refs:
            raw = review_artifacts.read(reference.artifact_id)
            assert (
                content.put(raw, media_type=reference.media_type)
                == reference.content_hash
            )
            store.publish_artifact(
                ArtifactRecordV1(
                    artifact_id=reference.artifact_id,
                    content_hash=reference.content_hash,
                    media_type=reference.media_type,
                    dependency_hashes=(),
                )
            )
        prepared = _run(runner, fixture.plan, candidate=candidate)
        preparation = SourcePreparationEvidenceV1.model_validate_json(
            artifacts.read(prepared.artifact.artifact_id)
        ).preparation
        approval = CallerApprovalEnvelopeV1(
            input_digest=preparation.input.input_digest,
            decision="approved",
            caller_id="operator",
            decided_at=VALUATION_TIME,
        )
        calculated = _run(runner, fixture.plan, approval=approval)
        evidence = SourcePreparationEvidenceV1.model_validate_json(
            artifacts.read(calculated.artifact.artifact_id)
        )
        assert evidence.status == "calculated"
        assert evidence.calculation.base.per_share_value > 0
        assert evidence.calculation.base.quality_status is QualityStatus.PROVISIONAL
        before = content_inventory()
        snapshot_count, fact_count = (
            len(store.list_snapshots()),
            len(store.list_facts()),
        )

        store.close()
        store = PostgresMetadataStore(
            source_database, auto_migrate=False, data_release_trust_roots=roots
        )
        store.start()
        restarted, _, restored_artifacts = wire(store)
        repeated = _run(
            restarted, fixture.plan, approval=approval, correlation="restart"
        )
        assert repeated.artifact == calculated.artifact
        assert repeated.wrote is False
        assert restored_artifacts.read(
            repeated.artifact.artifact_id
        ) == canonical_bytes(evidence)
        assert (len(store.list_snapshots()), len(store.list_facts())) == (
            snapshot_count,
            fact_count,
        )
        assert content_inventory() == before
        backup = asyncio.run(
            export_backup(
                source_database,
                tmp_path / "durable-content",
                tmp_path / "backups",
                source_revision=REVISION,
            )
        )
        bundle = tmp_path / "backups" / backup.manifest_digest
        restored_root = tmp_path / "restored-content"
        asyncio.run(
            restore_backup(
                target_database,
                restored_root,
                bundle,
                manifest_digest=backup.manifest_digest,
            )
        )
        recovered = PostgresMetadataStore(
            target_database, data_release_trust_roots=roots
        )
        recovered.start()
        try:
            restored_runner, _, restored_artifacts = wire(recovered, restored_root)
            restored_result = _run(
                restored_runner, fixture.plan, approval=approval, correlation="restore"
            )
            assert restored_result.artifact == calculated.artifact
            assert restored_result.wrote is False
            assert restored_artifacts.read(
                calculated.artifact.artifact_id
            ) == canonical_bytes(evidence)
            assert (len(recovered.list_snapshots()), len(recovered.list_facts())) == (
                snapshot_count,
                fact_count,
            )
        finally:
            recovered.close()
        assert (
            asyncio.run(
                export_backup(
                    target_database,
                    restored_root,
                    tmp_path / "backups",
                    source_revision=REVISION,
                )
            ).wrote
            is False
        )
    finally:
        store.close()


def test_plan_rejects_partial_model_requirements(tmp_path):
    fixture = _fixture(tmp_path)
    payload = fixture.plan.model_dump()
    payload["ingestions"] = (_sec_ingestion_request(),)
    with pytest.raises(ValueError, match="complete model requirements"):
        SourcePreparationPlanV2(**payload)


@pytest.mark.parametrize(
    "mismatch", ["order", "duplicate", "taxonomy_version", "ticker"]
)
def test_multi_original_plan_requires_sorted_distinct_accessions_and_shared_pins(
    tmp_path, mismatch
):
    fixture = _fixture(tmp_path)
    first = fixture.plan.ingestions[0]
    first = first.model_copy(
        update={
            "filing": first.filing.model_copy(
                update={"accession_number": "0000000001-24-000001", "forms": ("10-K",)}
            )
        }
    )
    second = first.model_copy(
        update={
            "filing": first.filing.model_copy(
                update={"accession_number": "0000000001-26-000001"}
            )
        }
    )
    requests = (first, second)
    if mismatch == "order":
        requests = requests[::-1]
    elif mismatch == "duplicate":
        requests = (first, first)
    else:
        requests = (first, second.model_copy(update={mismatch: "OTHER"}))
    with pytest.raises(ValueError):
        SourcePreparationPlanV2.model_validate(
            {**fixture.plan.model_dump(), "ingestions": requests}
        )


def test_multi_original_plan_covers_model_with_partial_per_filing_roles(tmp_path):
    fixture = _fixture(tmp_path)
    first = fixture.plan.ingestions[0]
    requests = []
    for index in range(2):
        fields = first.required_fields[index::2]
        requests.append(
            first.model_copy(
                update={
                    "required_fields": fields,
                    "mappings": tuple(
                        item
                        for item in first.mappings
                        if item.normalized_field in fields
                    ),
                    "filing": first.filing.model_copy(
                        update={
                            "accession_number": f"0000000001-{24 + index:02d}-000001",
                            "forms": ("10-K",),
                        }
                    ),
                }
            )
        )
    plan = SourcePreparationPlanV2.model_validate(
        {**fixture.plan.model_dump(), "ingestions": tuple(requests)}
    )
    assert plan.resolution_request().required_fields == first.required_fields
    assert (
        SourcePreparationPlanV2.model_validate_json(canonical_bytes(plan)).digest
        == plan.digest
    )


def test_multi_original_plan_acquires_composes_then_reuses_trusted_history(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    originals = tuple(_original(year) for year in (2023, 2025))
    first_request = fixture.plan.ingestions[0]
    requests = tuple(
        first_request.model_copy(
            update={
                "identity": original.identity,
                "cik": original.identity.issuer_id,
                "taxonomy_manifest_id": original.taxonomy_manifest_id,
                "policy_version": original.policy_version,
                "filing": first_request.filing.model_copy(
                    update={
                        "accession_number": original.sec_integrity_evidence.accession_number,
                        "forms": ("10-K",),
                    }
                ),
            }
        )
        for original in originals
    )
    plan = SourcePreparationPlanV2.model_validate(
        {**fixture.plan.model_dump(), "ingestions": requests}
    )
    facts = []
    for fact in fixture.facts.list():
        if fact.period_end.year < 2022:
            continue
        original = originals[0] if fact.period_end.year <= 2023 else originals[1]
        source = original.source_records[0]
        assert fact.period_end < source.available_at.date()
        facts.append(
            fact.model_copy(
                update={
                    "issuer_id": original.identity.issuer_id,
                    "security_id": original.identity.security_id,
                    "accession_number": source.accession_number,
                    "available_at": source.available_at,
                    "filed_at": source.filed_at,
                    "source": fact.source.model_copy(
                        update={
                            "content_hash": source.content_hash,
                            "source_url": source.uri,
                            "available_at": source.available_at,
                            "filed_at": source.filed_at,
                        }
                    ),
                }
            )
        )
    fact_repository = FilesystemCanonicalFactRepository(tmp_path / "history-facts")
    for fact in facts:
        fact_repository.publish(fact)
    fixture.facts = fact_repository
    fixture.application = replace(fixture.application, fact_repository=fact_repository)
    fixture.plan = plan
    calls = []

    def execute(request, **kwargs):
        calls.append(request.filing.accession_number)
        original = next(
            item
            for item in originals
            if item.sec_integrity_evidence.accession_number
            == request.filing.accession_number
        )
        fixture.snapshots.publish(original)
        return SecIngestionResponseV1(
            contract_version="fundamental.v1",
            status="created",
            identity=original.identity,
            valuation_timestamp=VALUATION_TIME,
            snapshot_id=original.snapshot_id,
            manifest_digest=original.manifest_digest,
            quality_status=QualityStatus.VERIFIED,
            parser_version="2.47.4",
            validation_profile_id="sec-efm-us-dqc-v31.0.3",
            validation_profile_digest="e" * 64,
            taxonomy_manifest_id="taxonomy-modern",
            taxonomy_version="us-gaap-modern",
            correlation_id=kwargs["correlation_id"],
        )

    runner = _runner(fixture, acquisition=SimpleNamespace(execute=execute))
    first = _reader(fixture, _run(runner, plan))
    assert first.status == "release_required"
    history = fixture.snapshots.get(first.snapshot_id)
    fixture.snapshot = history
    manifest = _release_manifest_for(history, tuple(facts))
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        profile_id=plan.release_profile_id,
        required_fields=first_request.required_fields,
        mapping_refs=fixture.manifest.mapping_refs,
    )
    fixture.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    candidate, canary = _reviewed_candidate(fixture)
    calls_before = tuple(calls)
    approved = _run(
        _runner(fixture, acquisition=SimpleNamespace(execute=execute), canary=canary),
        plan,
        candidate=candidate,
    )
    assert _reader(fixture, approved).status == "approval_required"
    assert tuple(calls) == calls_before
    preparation = _reader(fixture, approved).preparation
    approval = CallerApprovalEnvelopeV1(
        input_digest=preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    calculated = _run(_runner(fixture), plan, approval=approval)
    assert _reader(fixture, calculated).calculation.base.per_share_value > 0
    assert _run(_runner(fixture), plan, approval=approval).wrote is False
    assert tuple(calls) == calls_before
    altered = _changed(originals[0], policy_version="tampered")
    (fixture.snapshots.root / f"{originals[0].snapshot_id}.json").write_bytes(
        canonical_bytes(altered)
    )
    with pytest.raises(DataReleaseError) as error:
        canary.validate(candidate.manifest, candidate.verification)
    assert error.value.code == "DATA_RELEASE_HISTORY_COMPONENT_INVALID"
    for operation in (
        lambda: fixture.application.snapshot(history.snapshot_id),
        lambda: fixture.application.resolve_snapshot(plan.resolution_request()),
        lambda: _run(_runner(fixture), plan, approval=approval),
    ):
        with pytest.raises(ServiceError) as serving_error:
            operation()
        assert serving_error.value.code == "HISTORY_COMPONENT_MISMATCH"
    assert tuple(calls) == calls_before
    (fixture.snapshots.root / f"{originals[0].snapshot_id}.json").unlink()
    with pytest.raises(ServiceError) as missing_error:
        _run(runner, plan, approval=approval)
    assert missing_error.value.code == "HISTORY_COMPONENT_UNAVAILABLE"
    assert tuple(calls) == calls_before


def test_command_rejects_changed_plan_digest(tmp_path, capsys):
    fixture = _fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(canonical_bytes(fixture.plan))
    result = main(
        [
            "--plan",
            str(plan_path),
            "--plan-digest",
            "0" * 64,
            "--actor",
            "operator",
            "--organization",
            "operators",
        ]
    )
    assert result == 2
    assert "plan digest" in capsys.readouterr().err
