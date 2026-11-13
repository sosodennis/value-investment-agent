import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, Inexact, ROUND_DOWN, localcontext
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
    ArtifactRefV1,
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
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.quote_admission import QUOTE_ADMISSION_ROLE, QUOTE_TERMS_ROLE
from quote_provider_fixtures import publish_synthetic_quote_admission
from fundamental_service.replay import ArtifactRecordV1, ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository, SnapshotError
from fundamental_service.equity_award_evidence import (
    EQUITY_DILUTION_ARTIFACT_ROLE,
    EQUITY_QUOTE_SOURCE_ROLE,
)
from equity_award_fixtures import (
    award_evidence,
    quote_source_bytes,
    quote_source_payload,
)
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_api import _release_manifest_for
from test_postgres_metadata import DATABASE_URL, _sec_ingestion_request, _snapshot
from test_release_runner import _candidate
from test_history_composition import _changed, _original
from test_valuation_preparation import _facts
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from market_policy_fixtures import synthetic_policy_registry


REVISION = "1" * 40
VALUATION_TIME = datetime(2026, 3, 1, tzinfo=UTC)


def _fixture(
    tmp_path: Path,
    *,
    released: bool = True,
    namespace: str = "runner",
    empty_awards: bool = False,
    misaligned_history: bool = False,
    base_source_policy=None,
):
    source_bytes = b'{"source":"synthetic original filing fixture"}'
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    profile = valuation_requirements_profile("fcff_dcf")
    required = (
        *profile.required_fact_fields,
        *(profile.supporting_fact_fields[:2] if not empty_awards else ()),
    )
    mapped_fields = tuple(
        dict.fromkeys((*required, *(f.normalized_field for f in _facts())))
    )
    base = _sec_ingestion_request()
    ingestion = base.model_copy(
        update={
            "identity": base.identity.model_copy(
                update={"security_id": f"COMMON-{namespace.upper()[:24]}"}
            ),
            "valuation_timestamp": VALUATION_TIME,
            "required_fields": mapped_fields,
            "mappings": tuple(
                SecMappingReferenceV1(
                    decision_id=f"mapping-{field}",
                    mapping_version="mapping-v1",
                    normalized_field=field,
                )
                for field in mapped_fields
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
        for field in mapped_fields
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
    if misaligned_history:
        stored = tuple(
            fact.model_copy(
                update={
                    "period_start": date(2025, 1, 2),
                    "context": fact.context.model_copy(
                        update={"start_date": date(2025, 1, 2)}
                    ),
                }
            )
            if fact.normalized_field == "operating_income"
            and fact.period_end.year == 2025
            else fact
            for fact in stored
        )
    dilution = award_evidence(snapshot)
    if empty_awards:
        dilution = dilution.model_copy(
            update={
                "inventory": type(dilution.inventory).model_validate(
                    {**dilution.inventory.model_dump(), "instruments": ()}
                )
            }
        )
    stored = (
        *tuple(
            fact for fact in stored if fact.normalized_field != "dilutive_instruments"
        ),
        *dilution.facts,
    )
    for fact in stored:
        facts.publish(fact)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    source_use_policy, quote_refs = publish_synthetic_quote_admission(
        dilution.quote,
        quote_source_bytes(snapshot),
        valuation_at=snapshot.valuation_timestamp,
        artifacts=artifacts,
        base_policy=base_source_policy,
    )
    manifest = _release_manifest_for(snapshot, stored)
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        profile_id=plan.release_profile_id,
        required_fields=required,
        mapping_refs=tuple(
            MappingRefV1(mapping_id=key, mapping_digest=sha256_digest(mapping))
            for key, mapping in sorted(mappings.items())
        ),
        artifact_refs=(
            *manifest.artifact_refs,
            *quote_refs,
            ArtifactRefV1(
                artifact_id=f"equity-dilution:{dilution.digest}",
                content_hash=dilution.digest,
                media_type="application/json",
                role=EQUITY_DILUTION_ARTIFACT_ROLE,
            ),
            ArtifactRefV1(
                artifact_id="synthetic-quote",
                content_hash=hashlib.sha256(quote_source_bytes(snapshot)).hexdigest(),
                media_type="application/json",
                role=EQUITY_QUOTE_SOURCE_ROLE,
            ),
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
    artifacts.put_with_receipt(f"equity-dilution:{dilution.digest}", dilution)
    artifacts.put_with_receipt("synthetic-quote", quote_source_payload(snapshot))
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
        policy_registry=synthetic_policy_registry(),
        source_use_policy=source_use_policy,
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
        dilution=dilution,
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


def _runner(
    fixture,
    *,
    acquisition=None,
    canary=None,
    public_acquisition=None,
    public_admission=None,
):
    return SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=acquisition,
        artifacts=fixture.artifacts,
        canary=canary,
        public_acquisition=public_acquisition,
        public_admission=public_admission,
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


def _reviewed_candidate(fixture, *, quote_providers=None):
    seed_manifest, verification, _, _, _, artifacts, roots = _candidate()
    manifest_payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    manifest_payload.update(
        taxonomy_refs=seed_manifest.taxonomy_refs,
        artifact_refs=(
            *seed_manifest.artifact_refs,
            *(
                ref
                for ref in fixture.manifest.artifact_refs
                if ref.role
                in {
                    EQUITY_DILUTION_ARTIFACT_ROLE,
                    EQUITY_QUOTE_SOURCE_ROLE,
                    QUOTE_ADMISSION_ROLE,
                    QUOTE_TERMS_ROLE,
                }
            ),
        ),
    )
    manifest = DataReleaseManifestV1(
        **manifest_payload, manifest_digest=sha256_digest(manifest_payload)
    )
    review_artifacts = artifacts
    artifacts = SimpleNamespace(
        read=lambda artifact_id: fixture.artifacts.read(artifact_id)
        if artifact_id != "release-evidence"
        else review_artifacts.read(artifact_id)
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
        quote_providers=(
            default_quote_providers() if quote_providers is None else quote_providers
        ),
        source_use_policy=fixture.application.source_use_policy,
    )
    return candidate, canary


def test_released_source_uses_formal_composer_and_reuses_artifact_after_restart(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    runner = _runner(fixture)

    first = _run(runner, fixture.plan)
    prepared = _reader(fixture, first)
    with localcontext(Context(prec=7, rounding=ROUND_DOWN)) as context:
        context.traps[Inexact] = True
        repeated = _run(runner, fixture.plan, correlation="second")
    restarted = SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=None,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        canary=None,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        after_restart = pool.submit(_run, restarted, fixture.plan).result()

    assert prepared.status == "approval_required"
    assert prepared.preparation.status == "prepared"
    assert prepared.preparation.input.provenance.preparation_version == (
        "fcff-forecast-composer-v5"
    )
    assert prepared.preparation.input.assumptions.capital_bridge.lease_liabilities == (
        20
    )
    assert prepared.preparation.quality_status is QualityStatus.PROVISIONAL
    assert "HISTORY_THRESHOLD_UNVALIDATED" in prepared.preparation.issue_codes
    assert first.wrote is True
    assert repeated.wrote is False
    assert after_restart.wrote is False
    assert first.artifact == repeated.artifact == after_restart.artifact
    assert fixture.snapshot.manifest_digest in first.artifact.dependency_hashes


def test_history_conflict_is_persisted_and_reused_after_reopen(tmp_path):
    fixture = _fixture(tmp_path, misaligned_history=True)
    runner = _runner(fixture)

    first = _run(runner, fixture.plan)
    evidence = _reader(fixture, first)
    artifact_root = tmp_path / "artifacts"
    files_before = {
        item.name: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in artifact_root.glob("*.artifact")
    }
    repeated = _run(runner, fixture.plan, correlation="repeated-conflict")
    reopened = SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=None,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        canary=None,
    )
    after_reopen = _run(reopened, fixture.plan)

    assert evidence.status == "blocked"
    assert evidence.issue_codes == ("HISTORY_PERIOD_ALIGNMENT_CONFLICT",)
    assert evidence.snapshot_manifest_digest == fixture.snapshot.manifest_digest
    assert evidence.data_release_manifest_digest == fixture.manifest.manifest_digest
    assert evidence.preparation.status == "abstained"
    assert evidence.preparation.quality_status is QualityStatus.ABSTAIN
    assert evidence.preparation.input is None
    assert evidence.calculation is None
    assert first.wrote is True
    assert repeated.wrote is after_reopen.wrote is False
    assert first.artifact == repeated.artifact == after_reopen.artifact
    assert _reader(fixture, repeated) == _reader(fixture, after_reopen) == evidence
    assert files_before == {
        item.name: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in artifact_root.glob("*.artifact")
    }


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


@pytest.mark.parametrize("changed_pin", ["version", "decision", "role"])
def test_active_release_cannot_satisfy_different_plan_mapping(tmp_path, changed_pin):
    fixture = _fixture(tmp_path)
    request = fixture.plan.ingestions[0]
    references = list(request.mappings)
    if changed_pin == "version":
        references[0] = references[0].model_copy(
            update={"mapping_version": "mapping-v2"}
        )
    elif changed_pin == "decision":
        references[0] = references[0].model_copy(
            update={"decision_id": "other-mapping"}
        )
    else:
        first, second = references[:2]
        references[:2] = (
            first.model_copy(update={"normalized_field": second.normalized_field}),
            second.model_copy(update={"normalized_field": first.normalized_field}),
        )
    request = request.model_copy(update={"mappings": tuple(references)})
    plan = SourcePreparationPlanV2.model_validate(
        {**fixture.plan.model_dump(), "ingestions": (request,)}
    )
    acquisition = _acquisition(fixture)
    runner = _runner(fixture, acquisition=acquisition)

    first = _run(runner, plan)
    repeated = _run(runner, plan)

    assert _reader(fixture, first).status == "release_required"
    assert _reader(fixture, first).preparation is None
    assert repeated.wrote is False
    assert fixture.state.publications == 0


def test_candidate_mapping_mismatch_refuses_before_acquisition_or_publication(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    candidate, canary = _reviewed_candidate(fixture)
    request = fixture.plan.ingestions[0]
    reference = request.mappings[0].model_copy(update={"mapping_version": "mapping-v2"})
    plan = fixture.plan.model_copy(
        update={
            "ingestions": (
                request.model_copy(
                    update={"mappings": (reference, *request.mappings[1:])}
                ),
            )
        }
    )
    acquisition = _acquisition(fixture)

    with pytest.raises(ValueError, match="mappings"):
        _run(
            _runner(fixture, acquisition=acquisition, canary=canary),
            plan,
            candidate=candidate,
        )

    assert acquisition.calls == []
    assert fixture.state.publications == 0
    assert fixture.state.active is None


def test_release_cannot_substitute_another_reviewed_mapping_for_source_facts(tmp_path):
    fixture = _fixture(tmp_path)
    request = fixture.plan.ingestions[0]
    reference = request.mappings[0]
    mapping = fixture.mappings[reference.decision_id].model_copy(
        update={"decision_id": "alternate-reviewed-mapping"}
    )
    fixture.mappings[mapping.decision_id] = mapping
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload["mapping_refs"] = (
        *fixture.manifest.mapping_refs,
        MappingRefV1(
            mapping_id=mapping.decision_id, mapping_digest=sha256_digest(mapping)
        ),
    )
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    fixture.state.active = fixture.active.model_copy(
        update={
            "manifest": manifest,
            "active": fixture.active.active.model_copy(
                update={"manifest_digest": manifest.manifest_digest}
            ),
        }
    )
    fixture.metadata.get_data_release_manifest = lambda digest: (
        manifest if digest == manifest.manifest_digest else None
    )
    plan = fixture.plan.model_copy(
        update={
            "ingestions": (
                request.model_copy(
                    update={
                        "mappings": (
                            reference.model_copy(
                                update={"decision_id": mapping.decision_id}
                            ),
                            *request.mappings[1:],
                        )
                    }
                ),
            )
        }
    )

    receipt = _run(_runner(fixture, acquisition=_acquisition(fixture)), plan)

    assert _reader(fixture, receipt).status == "release_required"
    assert _reader(fixture, receipt).calculation is None


def test_changed_mapping_content_is_corruption_and_never_triggers_acquisition(tmp_path):
    fixture = _fixture(tmp_path)
    reference = fixture.plan.ingestions[0].mappings[0]
    fixture.mappings[reference.decision_id] = fixture.mappings[
        reference.decision_id
    ].model_copy(update={"source_concept": "us-gaap:WrongRole"})
    acquisition = _acquisition(fixture)

    with pytest.raises(ServiceError) as error:
        _run(_runner(fixture, acquisition=acquisition), fixture.plan)

    assert error.value.code == "DATA_RELEASE_MAPPING_MISMATCH"
    assert acquisition.calls == []


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
    with pytest.raises(ServiceError, match="authenticated subject"):
        _run(
            runner,
            fixture.plan,
            approval=approval.model_copy(update={"caller_id": "other"}),
        )


@pytest.mark.parametrize("invalid", ["caller", "future"])
def test_unbound_approval_refuses_before_source_or_release_access(
    tmp_path, monkeypatch, invalid
):
    fixture = _fixture(tmp_path)
    runner = _runner(fixture)
    reached = []

    def resolve(*args):
        reached.append("resolve")
        raise AssertionError("invalid approval reached stored source resolution")

    monkeypatch.setattr(runner, "_resolve", resolve)
    approval = CallerApprovalEnvelopeV1(
        input_digest="a" * 64,
        decision="approved",
        caller_id="someone-else" if invalid == "caller" else "operator",
        decided_at=datetime.now(UTC) + timedelta(days=1)
        if invalid == "future"
        else VALUATION_TIME,
    )
    with pytest.raises(ServiceError) as error:
        _run(runner, fixture.plan, approval=approval)

    assert error.value.code == (
        "CALLER_APPROVAL_IDENTITY_MISMATCH"
        if invalid == "caller"
        else "CALLER_APPROVAL_NOT_YET_DECIDED"
    )
    assert error.value.status_code == 403
    assert error.value.retryable is False
    assert reached == []


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
def test_incomplete_acquisition_stays_blocked_and_reuses_evidence_after_restore(
    tmp_path, recovery_databases
):
    from fundamental_service.source_acquisition import SecAcquisitionUseCase
    from test_source_acquisition import _partial_acquisition_fixture

    source_database, target_database = recovery_databases
    fixture = _partial_acquisition_fixture(tmp_path)
    fields = valuation_requirements_profile("fcff_dcf").required_fact_fields
    mappings = tuple(
        CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=f"partial-{field}",
            source_concept=f"us-gaap:{field}",
            normalized_field=field,
            mapping_version="partial-v1",
            status="provisional",
            confidence="unresolved",
        )
        for field in fields
    )
    request = fixture.request.model_copy(
        update={
            "required_fields": fields,
            "mappings": tuple(
                SecMappingReferenceV1(
                    decision_id=mapping.decision_id,
                    mapping_version=mapping.mapping_version,
                    normalized_field=mapping.normalized_field,
                )
                for mapping in mappings
            ),
        }
    )
    plan = SourcePreparationPlanV2(
        source_revision=REVISION,
        release_profile_id="incomplete-source-test-v1",
        model_id="fcff_dcf",
        ingestions=(request,),
    )

    def wire(metadata, content_root):
        content = PostgresContentStore(content_root, metadata)
        artifacts = PostgresArtifactStore(metadata, content)
        application = create_app(
            snapshot_repository=PostgresSnapshotRepository(metadata),
            fact_repository=PostgresCanonicalFactRepository(metadata),
            content_store=content,
            artifact_store=artifacts,
            metadata_store=metadata,
            config=OperationsConfig.testing(),
            policy_registry=synthetic_policy_registry(),
        ).state.application
        acquisition = SecAcquisitionUseCase(
            adapter=fixture.provider,
            ingestion=fixture.ingestion,
            metadata=metadata,
            content_store=content,
            settings=fixture.settings,
            authorized_organizations=frozenset({"operators"}),
            capture_store=artifacts,
        )
        return (
            SourcePreparationRunner(
                application=application,
                metadata=metadata,
                acquisition=acquisition,
                artifacts=artifacts,
                canary=None,
            ),
            content,
            artifacts,
        )

    def invoke(runner):
        return runner.run(
            plan,
            actor_id="operator",
            organization_id="operators",
            correlation_id="incomplete-source",
            deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        )

    content_root = tmp_path / "durable-content"
    store = PostgresMetadataStore(source_database, auto_migrate=True)
    store.start()
    try:
        for mapping in mappings:
            store.publish_mapping(mapping)
        runner, content, artifacts = wire(store, content_root)
        source = fixture.snapshot.source_records[0]
        content.put(
            fixture.content.get(source.content_hash, media_type=source.media_type),
            media_type=source.media_type,
        )
        first = invoke(runner)
        evidence = SourcePreparationEvidenceV1.model_validate_json(
            artifacts.read(first.artifact.artifact_id)
        )
        assert evidence.status == "blocked"
        assert evidence.issue_codes == ("REQUIRED_FACTS_UNAVAILABLE",)
        assert evidence.missing_evidence == tuple(sorted(set(fields) - {"revenue"}))
        assert evidence.snapshot_id == fixture.snapshot.snapshot_id
        assert evidence.snapshot_manifest_digest == fixture.snapshot.manifest_digest
        assert evidence.preparation is None and evidence.calculation is None
        assert store.get_snapshot(evidence.snapshot_id) == fixture.snapshot
        assert store.get_fact(fixture.facts[0].fact_id) == fixture.facts[0]
        assert fixture.facts[0].quality is QualityStatus.PROVISIONAL
        assert fixture.state.parser_calls == 1
        calls = fixture.state.provider_calls
        inventory = tuple(
            (str(p.relative_to(content_root)), p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(content_root.rglob("*"))
            if p.is_file()
        )
    finally:
        store.close()
    reopened = PostgresMetadataStore(source_database)
    reopened.start()
    try:
        runner, _, artifacts = wire(reopened, content_root)
        for _ in range(2):
            repeated = invoke(runner)
            assert repeated == first.model_copy(update={"wrote": False})
            assert artifacts.read(repeated.artifact.artifact_id) == canonical_bytes(
                evidence
            )
        assert fixture.state.provider_calls == calls
        assert fixture.state.parser_calls == 1
        assert len(reopened.list_snapshots()) == len(reopened.list_facts()) == 1
        assert (
            tuple(
                (str(p.relative_to(content_root)), p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted(content_root.rglob("*"))
                if p.is_file()
            )
            == inventory
        )
    finally:
        reopened.close()
    backup = asyncio.run(
        export_backup(
            source_database,
            content_root,
            tmp_path / "backups",
            source_revision=REVISION,
        )
    )
    restored_root = tmp_path / "restored-content"
    asyncio.run(
        restore_backup(
            target_database,
            restored_root,
            tmp_path / "backups" / backup.manifest_digest,
            manifest_digest=backup.manifest_digest,
        )
    )
    restored = PostgresMetadataStore(target_database)
    restored.start()
    try:
        runner, _, artifacts = wire(restored, restored_root)
        receipt = invoke(runner)
        assert receipt == first.model_copy(update={"wrote": False})
        assert artifacts.read(receipt.artifact.artifact_id) == canonical_bytes(evidence)
        assert restored.get_snapshot(evidence.snapshot_id) == fixture.snapshot
        assert restored.get_fact(fixture.facts[0].fact_id) == fixture.facts[0]
        assert len(restored.list_snapshots()) == len(restored.list_facts()) == 1
        assert fixture.state.provider_calls == calls
        assert fixture.state.parser_calls == 1
    finally:
        restored.close()


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL is required")
@pytest.mark.parametrize("empty_awards", [False, True])
@pytest.mark.parametrize("acquire_public", [False, True])
def test_preparation_and_calculation_reuse_postgres_artifacts_after_restart_and_restore(
    tmp_path, recovery_databases, empty_awards, acquire_public
):
    source_database, target_database = recovery_databases
    fixture = _fixture(
        tmp_path, released=False, namespace=uuid4().hex, empty_awards=empty_awards
    )
    from fundamental_service.public_acquisition import (
        PostgresPublicCaptureLock,
        PublicSourceAcquisition,
    )

    plan = fixture.plan
    public_provider = None
    if acquire_public:
        public_provider, _, plan = _public_source_fixture(fixture, tmp_path)
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
            policy_registry=synthetic_policy_registry(),
            source_use_policy=fixture.application.source_use_policy,
        ).state.application
        runner = SourcePreparationRunner(
            application=application,
            metadata=metadata,
            acquisition=None,
            artifacts=artifacts,
            public_acquisition=PublicSourceAcquisition(
                provider=public_provider,
                artifacts=artifacts,
                content=content,
                capture_lock=PostgresPublicCaptureLock(metadata),
            )
            if public_provider is not None
            else None,
            canary=DataReleaseCanaryRunner(
                snapshot_repository=application.snapshot_repository,
                fact_repository=application.fact_repository,
                mapping_reader=metadata,
                artifact_reader=artifacts,
                trust_roots=roots,
                quote_providers=application.quote_providers,
                source_use_policy=application.source_use_policy,
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
            raw = (
                fixture.artifacts
                if reference.role
                in {
                    EQUITY_DILUTION_ARTIFACT_ROLE,
                    EQUITY_QUOTE_SOURCE_ROLE,
                    QUOTE_ADMISSION_ROLE,
                    QUOTE_TERMS_ROLE,
                }
                else review_artifacts
            ).read(reference.artifact_id)
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
        prepared = _run(runner, plan, candidate=candidate)
        preparation = SourcePreparationEvidenceV1.model_validate_json(
            artifacts.read(prepared.artifact.artifact_id)
        ).preparation
        approval = CallerApprovalEnvelopeV1(
            input_digest=preparation.input.input_digest,
            decision="approved",
            caller_id="operator",
            decided_at=VALUATION_TIME,
        )
        calculated = _run(runner, plan, approval=approval)
        evidence = SourcePreparationEvidenceV1.model_validate_json(
            artifacts.read(calculated.artifact.artifact_id)
        )
        assert evidence.status == "calculated"
        assert bool(evidence.public_source_outcomes) is acquire_public
        assert evidence.calculation.base.per_share_value > 0
        assert evidence.calculation.base.quality_status is QualityStatus.PROVISIONAL
        assert (
            evidence.preparation.input.assumptions.capital_bridge.non_operating_assets
            == Decimal(10)
        )
        assert evidence.calculation.base.model_version == "fcff_dcf-v2"
        assert evidence.preparation.equity_dilution.incremental_shares == (
            0 if empty_awards else 10
        )
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
        with localcontext(Context(prec=7, rounding=ROUND_DOWN)) as context:
            context.traps[Inexact] = True
            repeated = _run(restarted, plan, approval=approval, correlation="restart")
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
            with ThreadPoolExecutor(max_workers=1) as pool:
                restored_result = pool.submit(
                    _run,
                    restored_runner,
                    plan,
                    approval=approval,
                    correlation="restore",
                ).result()
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
        if public_provider is not None:
            assert len(public_provider.calls) == 1
    finally:
        store.close()


def test_plan_rejects_partial_model_requirements(tmp_path):
    fixture = _fixture(tmp_path)
    payload = fixture.plan.model_dump()
    payload["ingestions"] = (_sec_ingestion_request(),)
    with pytest.raises(ValueError, match="complete model requirements"):
        SourcePreparationPlanV2(**payload)


@pytest.mark.parametrize(
    "mismatch",
    [
        "order",
        "duplicate",
        "taxonomy_version",
        "ticker",
        "mapping_version",
        "mapping_role",
    ],
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
    elif mismatch in {"mapping_version", "mapping_role"}:
        references = list(second.mappings)
        if mismatch == "mapping_version":
            references[0] = references[0].model_copy(
                update={"mapping_version": "different-version"}
            )
        else:
            left, right = references[:2]
            references[:2] = (
                left.model_copy(update={"normalized_field": right.normalized_field}),
                right.model_copy(update={"normalized_field": left.normalized_field}),
            )
        requests = (first, second.model_copy(update={"mappings": tuple(references)}))
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
    assert (
        plan.resolution_request().required_fields
        == valuation_requirements_profile("fcff_dcf").required_fact_fields
    )
    assert (
        SourcePreparationPlanV2.model_validate_json(canonical_bytes(plan)).digest
        == plan.digest
    )


@pytest.mark.parametrize(
    "partial_case",
    [
        "complete",
        "earlier_capital_gap",
        "aggregate_capital_gap",
        "future_capital_fact",
        "foreign_mapping",
        "annual_gap",
        "annual_conflict",
        "source_integrity",
        "snapshot_digest",
    ],
)
def test_multi_original_plan_acquires_composes_then_reuses_trusted_history(
    tmp_path, partial_case
):
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
                    "security_scope": original.identity.security_id,
                    "context": fact.context.model_copy(
                        update={"entity_scope": original.identity.issuer_id}
                    ),
                    "source": fact.source.model_copy(
                        update={
                            "content_hash": source.content_hash,
                            "source_url": source.uri,
                            "available_at": source.available_at,
                            "filed_at": source.filed_at,
                            "accession_number": source.accession_number,
                        }
                    ),
                }
            )
        )
    if partial_case == "aggregate_capital_gap":
        facts = [f for f in facts if f.normalized_field != "non_operating_assets"]
    elif partial_case in {"future_capital_fact", "foreign_mapping"}:
        facts = [
            fact.model_copy(
                update={"available_at": VALUATION_TIME + timedelta(days=1)}
                if partial_case == "future_capital_fact"
                else {"mapping_decision_id": "another-plan-mapping"}
            )
            if fact.normalized_field == "non_operating_assets"
            else fact
            for fact in facts
        ]
    elif partial_case == "annual_gap":
        facts = [
            f
            for f in facts
            if not (f.normalized_field == "revenue" and f.period_end.year == 2024)
        ]
    elif partial_case == "annual_conflict":
        conflict = next(
            f
            for f in facts
            if f.normalized_field == "revenue" and f.period_end.year == 2024
        )
        facts.append(
            conflict.model_copy(
                update={"fact_id": "conflicting-revenue", "value": conflict.value + 1}
            )
        )
    if partial_case == "source_integrity":
        originals = (
            _changed(originals[0], coverage_status=QualityStatus.PROVISIONAL),
            originals[1],
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
        incomplete = partial_case != "complete" and original == originals[0]
        return SecIngestionResponseV1(
            contract_version="fundamental.v1",
            status="abstain" if incomplete else "created",
            identity=original.identity,
            valuation_timestamp=VALUATION_TIME,
            snapshot_id=original.snapshot_id,
            manifest_digest=(
                "0" * 64
                if incomplete and partial_case == "snapshot_digest"
                else original.manifest_digest
            ),
            quality_status=QualityStatus.ABSTAIN
            if incomplete
            else QualityStatus.VERIFIED,
            issue_codes=("REQUIRED_FACTS_UNAVAILABLE",) if incomplete else (),
            missing_evidence=("non_operating_assets",) if incomplete else (),
            parser_version="2.47.4",
            validation_profile_id="sec-efm-us-dqc-v31.0.3",
            validation_profile_digest="e" * 64,
            taxonomy_manifest_id="taxonomy-modern",
            taxonomy_version="us-gaap-modern",
            correlation_id=kwargs["correlation_id"],
        )

    runner = _runner(fixture, acquisition=SimpleNamespace(execute=execute))
    publication = _run(runner, plan)
    first = _reader(fixture, publication)
    assert len(first.source_outcomes) == 2
    if partial_case not in {"complete", "earlier_capital_gap"}:
        assert first.status == "blocked"
        expected_issue = {
            "aggregate_capital_gap": "VALUATION_REQUIRED_FACTS_MISSING",
            "future_capital_fact": "VALUATION_REQUIRED_FACTS_MISSING",
            "foreign_mapping": "VALUATION_REQUIRED_FACTS_MISSING",
            "annual_gap": "HISTORY_MINIMUM_PERIODS_UNAVAILABLE",
            "annual_conflict": "HISTORY_FACT_CONFLICT",
            "source_integrity": "REQUIRED_FACTS_UNAVAILABLE",
            "snapshot_digest": "ACQUIRED_SNAPSHOT_MISMATCH",
        }[partial_case]
        assert expected_issue in first.issue_codes
        before = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in tmp_path.rglob("*")
            if p.is_file()
        }
        assert _run(runner, plan) == publication.model_copy(update={"wrote": False})
        assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
        assert fixture.state.active is None
        return
    assert first.status == "release_required"
    if partial_case == "earlier_capital_gap":
        assert first.source_outcomes[0].quality_status is QualityStatus.ABSTAIN
        assert first.source_outcomes[0].source_coverage_status is QualityStatus.VERIFIED
        assert first.source_outcomes[0].missing_evidence == ("non_operating_assets",)
        assert first.missing_evidence == ()
    history = fixture.snapshots.get(first.snapshot_id)
    fixture.snapshot = history
    award_facts = {
        fact.normalized_field: fact
        for fact in facts
        if fact.normalized_field.startswith("equity_award_")
    }
    award = fixture.dilution.inventory.instruments[0].model_copy(
        update={
            "quantity": award_facts["equity_award_quantity"],
            "unrecognized_compensation": award_facts[
                "equity_award_unrecognized_compensation"
            ],
        }
    )
    inventory = fixture.dilution.inventory.model_copy(
        update={
            "issuer_id": history.identity.issuer_id,
            "security_id": history.identity.security_id,
            "coverage_evidence": fixture.dilution.inventory.coverage_evidence.model_copy(
                update={"source_refs": (award.quantity.source.content_hash,)}
            ),
            "instruments": (award,),
        }
    )
    from zoneinfo import ZoneInfo

    from fundamental_service.quote_sources import select_nasdaq_historical_close

    observation_date = history.valuation_timestamp.astimezone(
        ZoneInfo("America/New_York")
    ).date() - timedelta(days=1)
    quote_bytes = quote_source_bytes(history)
    quote = select_nasdaq_historical_close(
        quote_bytes,
        issuer_id=history.identity.issuer_id,
        security_id=history.identity.security_id,
        source_uri=(
            f"https://api.nasdaq.com/api/quote/{history.identity.security_id}/historical"
            f"?assetclass=stocks&fromdate={observation_date.isoformat()}"
            f"&todate={(observation_date + timedelta(days=1)).isoformat()}&limit=10"
        ),
        observation_date=observation_date,
        captured_at=history.valuation_timestamp,
    )
    quote_artifact_id = f"quote-source:{quote.content_hash}"
    fixture.artifacts.put_bytes_with_receipt(
        quote_artifact_id, quote_bytes, media_type="application/json"
    )
    fixture.dilution = fixture.dilution.model_copy(
        update={
            "snapshot_manifest_digest": history.manifest_digest,
            "inventory": inventory,
            "quote": quote,
        }
    )
    fixture.artifacts.put_with_receipt(
        f"equity-dilution:{fixture.dilution.digest}", fixture.dilution
    )
    manifest = _release_manifest_for(history, tuple(facts))
    source_use_policy, quote_refs = publish_synthetic_quote_admission(
        quote,
        quote_bytes,
        valuation_at=history.valuation_timestamp,
        artifacts=fixture.artifacts,
    )
    fixture.application = replace(
        fixture.application, source_use_policy=source_use_policy
    )
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        profile_id=plan.release_profile_id,
        required_fields=first_request.required_fields,
        mapping_refs=fixture.manifest.mapping_refs,
        artifact_refs=(
            *manifest.artifact_refs,
            *quote_refs,
            ArtifactRefV1(
                artifact_id=f"equity-dilution:{fixture.dilution.digest}",
                content_hash=fixture.dilution.digest,
                media_type="application/json",
                role=EQUITY_DILUTION_ARTIFACT_ROLE,
            ),
            *(
                ref.model_copy(
                    update={
                        "artifact_id": quote_artifact_id,
                        "content_hash": quote.content_hash,
                    }
                )
                for ref in fixture.manifest.artifact_refs
                if ref.role == EQUITY_QUOTE_SOURCE_ROLE
            ),
        ),
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
    assert _reader(fixture, approved).source_outcomes == first.source_outcomes
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
    assert _reader(fixture, calculated).source_outcomes == first.source_outcomes
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


def _public_source_fixture(fixture, tmp_path):
    from test_public_acquisition import Provider, acquisition, request

    provider = Provider()
    provider.source = replace(
        provider.source,
        available_at=VALUATION_TIME - timedelta(hours=1),
        captured_at=VALUATION_TIME - timedelta(hours=1),
    )
    source_request = request(valuation_timestamp=VALUATION_TIME)
    plan = SourcePreparationPlanV2.model_validate(
        {
            **fixture.plan.model_dump(),
            "public_sources": (source_request,),
        }
    )
    use_case = acquisition(tmp_path / "public", provider, artifacts=fixture.artifacts)
    return provider, use_case, plan


def test_required_public_source_runs_before_formal_preparation_and_reuses_report(
    tmp_path,
):
    from test_public_acquisition import inventory

    fixture = _fixture(tmp_path)
    provider, use_case, plan = _public_source_fixture(fixture, tmp_path)
    runner = _runner(fixture, public_acquisition=use_case)
    first = _run(runner, plan)
    report = _reader(fixture, first)
    assert report.status == "approval_required"
    assert report.preparation.status == "prepared"
    baseline = _reader(fixture, _run(_runner(fixture), fixture.plan))
    assert report.preparation == baseline.preparation
    assert report.public_source_outcomes[0].source.source_id == "damodaran-reference"
    assert report.public_source_outcomes[0].digest in first.artifact.dependency_hashes
    before = inventory(tmp_path)
    second = _run(
        _runner(fixture, public_acquisition=use_case), plan, correlation="repeat"
    )
    assert second.artifact == first.artifact and not second.wrote
    assert inventory(tmp_path) == before and len(provider.calls) == 1
    assert plan.digest != fixture.plan.digest


def test_required_public_source_after_cutoff_blocks_even_existing_release(tmp_path):
    fixture = _fixture(tmp_path)
    provider, use_case, plan = _public_source_fixture(fixture, tmp_path)
    provider.source = replace(
        provider.source,
        available_at=VALUATION_TIME + timedelta(hours=1),
        captured_at=VALUATION_TIME + timedelta(hours=1),
    )
    first = _run(_runner(fixture, public_acquisition=use_case), plan)
    report = _reader(fixture, first)
    assert report.status == "blocked" and report.preparation is None
    assert report.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    assert report.public_source_outcomes[0].source is not None
    second = _run(_runner(fixture, public_acquisition=use_case), plan)
    assert second.artifact == first.artifact and not second.wrote
    assert len(provider.calls) == 1


def test_public_source_failure_retains_all_required_sources_and_stable_report(tmp_path):
    fixture = _fixture(tmp_path)
    provider, use_case, plan = _public_source_fixture(fixture, tmp_path)
    source_request = plan.public_sources[0]
    other = source_request.model_copy(
        update={"uri": source_request.uri.replace("ctryprem.xlsx", "wacc.xls")}
    )
    plan = SourcePreparationPlanV2.model_validate(
        {**plan.model_dump(), "public_sources": (source_request, other)}
    )
    capture = provider.capture

    def partly_failing(source_id, uri):
        if uri == source_request.uri:
            provider.calls.append((source_id, uri))
            raise SnapshotError("SOURCE_PAYLOAD_INVALID", "source fixture")
        return capture(source_id, uri)

    provider.capture = partly_failing
    first = _run(_runner(fixture, public_acquisition=use_case), plan)
    report = _reader(fixture, first)
    assert report.status == "blocked" and report.preparation is None
    assert report.issue_codes == ("SOURCE_PAYLOAD_INVALID",)
    assert tuple(x.status for x in report.public_source_outcomes) == (
        "failed",
        "captured",
    )
    assert (
        tuple(x.request for x in report.public_source_outcomes) == plan.public_sources
    )
    second = _run(_runner(fixture, public_acquisition=use_case), plan)
    assert second.artifact == first.artifact and not second.wrote
    assert len(provider.calls) == 2


def test_public_sources_require_configured_acquisition(tmp_path):
    fixture = _fixture(tmp_path)
    _, _, plan = _public_source_fixture(fixture, tmp_path)
    with pytest.raises(ServiceError) as failure:
        _run(_runner(fixture), plan)
    assert failure.value.code == "PUBLIC_SOURCE_ACQUISITION_UNAVAILABLE"


@pytest.mark.parametrize("kind", ["duplicate", "date"])
def test_public_source_plan_rejects_duplicates_and_mixed_valuation_dates(
    tmp_path, kind
):
    fixture = _fixture(tmp_path)
    _, _, plan = _public_source_fixture(fixture, tmp_path)
    source_request = plan.public_sources[0]
    requests = (
        (source_request, source_request)
        if kind == "duplicate"
        else (
            source_request.model_copy(
                update={"valuation_timestamp": VALUATION_TIME + timedelta(days=1)}
            ),
        )
    )
    with pytest.raises(ValueError, match="distinct and pin plan date"):
        SourcePreparationPlanV2.model_validate(
            {**plan.model_dump(), "public_sources": requests}
        )


def test_invalid_candidate_refuses_before_required_public_source_io(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    provider, use_case, plan = _public_source_fixture(fixture, tmp_path)
    candidate, _ = _reviewed_candidate(fixture)
    changed = candidate.model_copy(
        update={
            "manifest": candidate.manifest.model_copy(
                update={"profile_id": "different-profile"}
            )
        }
    )
    with pytest.raises(ValueError, match="candidate does not match"):
        _run(_runner(fixture, public_acquisition=use_case), plan, candidate=changed)
    assert provider.calls == []


def test_command_reports_stable_source_refusal_code_and_retryability(
    monkeypatch, capsys
):
    import json
    import fundamental_service.preparation_runner as command

    async def busy(_args):
        raise SnapshotError(
            "PUBLIC_CAPTURE_IN_PROGRESS", "identical capture is busy", retryable=True
        )

    monkeypatch.setattr(command, "_run_command", busy)
    args = [
        "--plan",
        "unused.json",
        "--plan-digest",
        "a" * 64,
        "--actor",
        "operator",
        "--organization",
        "operators",
    ]
    assert command.main(args) == 2
    first = capsys.readouterr()
    result = json.loads(first.err)
    assert result["protocol"] == "source-preparation-error-v1"
    assert (
        result["code"] == "PUBLIC_CAPTURE_IN_PROGRESS" and result["retryable"] is True
    )
    assert result["plan_digest"] == "a" * 64
    assert command.main(args) == 2
    assert capsys.readouterr().err == first.err
