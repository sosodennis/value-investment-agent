import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fundamental_service.classification_crosswalk import ClassificationCrosswalkPolicyV1
from fundamental_service.contracts import SourceRecordV1, SourceRole
from fundamental_service.automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_REF_PREFIX,
    load_release_automatic_market_policy,
)
from fundamental_service.data_releases import DataReleaseManifestV1
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.policies import PolicyRecordV1
from fundamental_service.current_preparation import CurrentSourcePreparationRequestV1
from fundamental_service.issuer_country_crosswalk import CountryCrosswalkPolicyV1
from fundamental_service.issuer_market_policy_plan import (
    IssuerMarketReferencePlanPolicyV1,
)
from fundamental_service.issuer_market_preparation import (
    IssuerMarketPreparation,
    IssuerMarketPreparationEvidenceV1,
    IssuerMarketPreparationRequestV1,
)
from fundamental_service.preparation_runner import SourcePreparationRunner
from fundamental_service.source_plan_contracts import SOURCE_PREPARATION_PLAN
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_classification_snapshot import (
    SecSnapshotClassificationSources,
)
from fundamental_service.sec_classification_source import (
    SecSubmissionClassificationProvider,
)
from fundamental_service.sec_sic_damodaran_crosswalk import (
    SecSicDamodaranIndustryCrosswalk,
)
from fundamental_service.sec_source import SEC_TERMS
from fundamental_service.sec_state_country_crosswalk import SecStateCountryCrosswalk
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.source_evidence import RetainedSourceV1
from test_automatic_market_policy import AT, _admissions, _market_policy, _plan_decision
from test_current_preparation import current_fixture, select
from test_history_composition import _changed
from test_issuer_classification import (
    ACCEPTED,
    CAPTURED,
    AlternateJsonClassificationProvider,
    request,
    sec_submission,
)
from test_postgres_metadata import _snapshot
from test_automatic_market_policy_evidence import _bound
from test_preparation_runner import (
    REVISION,
    _fixture,
    _reader,
    _reviewed_candidate,
    _run,
)
from test_public_acquisition import inventory


def market_request(at=AT, *, issuer_id="0000320193", accession=None):
    country = SecStateCountryCrosswalk()
    industry = SecSicDamodaranIndustryCrosswalk()
    market = _market_policy(at)
    market = market.model_copy(
        update={
            "terminal_growth_plan": market.terminal_growth_plan.model_copy(
                update={"issuer_id": issuer_id}
            )
        }
    )
    classification = request(valuation_at=at, issuer_id=issuer_id)
    if accession is not None:
        classification = classification.model_copy(
            update={"accession_number": accession}
        )
    return IssuerMarketPreparationRequestV1(
        source_revision=REVISION,
        classification_provider_id=SecSubmissionClassificationProvider.provider_id,
        classification_request=classification,
        country_policy=CountryCrosswalkPolicyV1(
            provider_id=country.provider_id,
            mapping_version=country.mapping_version,
            mapping_digest=country.mapping_digest,
            source_scheme="sec-state-country-v1",
            target_taxonomy=country.target_taxonomy,
        ),
        industry_policy=ClassificationCrosswalkPolicyV1(
            provider_id=industry.provider_id,
            mapping_version=industry.mapping_version,
            mapping_digest=industry.mapping_digest,
            source_scheme="sec-sic-v1",
            target_taxonomy=industry.target_taxonomy,
        ),
        reference_policy=IssuerMarketReferencePlanPolicyV1(),
        market_policy=market,
    )


def preparer(artifacts, content):
    return IssuerMarketPreparation(
        classification_provider=SecSubmissionClassificationProvider(),
        classification_sources=SecSnapshotClassificationSources(content),
        country_provider=SecStateCountryCrosswalk(),
        industry_provider=SecSicDamodaranIndustryCrosswalk(),
        artifacts=artifacts,
    )


def fixture(tmp_path, *, sic="ELECTRONIC COMPUTERS [3571]"):
    original = sec_submission(sic=sic)
    content = FilesystemContentStore(tmp_path / "originals")
    digest = content.put(original.content, media_type="text/plain")
    base = _snapshot("market", valuation_timestamp=AT)
    snapshot = _changed(
        base,
        identity=base.identity.model_copy(update={"issuer_id": "0000320193"}),
        captured_at=CAPTURED,
        source_records=(
            SourceRecordV1(
                source_id="sec-filing-submission",
                uri=original.uri,
                role=SourceRole.FILING,
                available_at=ACCEPTED,
                captured_at=CAPTURED,
                http_status=200,
                media_type="text/plain",
                terms_reference=SEC_TERMS,
                content_hash=digest,
                parser_version="existing-sec-parser",
                accession_number=request().accession_number,
                form="10-K",
            ),
        ),
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    return SimpleNamespace(
        original=original,
        content=content,
        snapshot=snapshot,
        artifacts=artifacts,
        request=market_request(),
        preparation=preparer(artifacts, content),
    )


def execute(f, *, admissions=None, **kwargs):
    return f.preparation.execute(
        f.request,
        snapshot=f.snapshot,
        admissions=_admissions(AT) if admissions is None else admissions,
        **kwargs,
    )


def test_preparation_uses_formal_existing_policies_and_publishes_exact_release_inputs(
    tmp_path,
):
    f = fixture(tmp_path)
    evidence, publication = execute(f)
    assert publication.wrote and not evidence.issue_codes
    assert evidence.market.decision.status == "approved"
    assert evidence.market.decision.inputs is not None
    assert evidence.market.plan_decision.plan == _plan_decision().plan
    assert (
        evidence.classification.source_artifacts[0].content_sha256
        == sha256(f.original.content).hexdigest()
    )
    assert evidence.classification.source_artifacts[0].terms_reference == SEC_TERMS
    assert len(evidence.release_refs) == 4
    for ref in evidence.release_refs:
        assert sha256(f.artifacts.read(ref.artifact_id)).hexdigest() == ref.content_hash
    assert f.artifacts.read(publication.artifact.artifact_id) == canonical_bytes(
        evidence
    )
    assert (
        IssuerMarketPreparationEvidenceV1.model_validate_json(canonical_bytes(evidence))
        == evidence
    )


def test_repeat_reopen_and_concurrent_reorders_reuse_every_artifact_unchanged(tmp_path):
    f = fixture(tmp_path)
    first, publication = execute(f)
    before = inventory(tmp_path)

    def repeat(_):
        store = ArtifactStore(tmp_path / "artifacts")
        return preparer(store, f.content).execute(
            f.request,
            snapshot=f.snapshot,
            admissions=tuple(reversed(_admissions(AT))),
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        repeats = tuple(pool.map(repeat, range(3)))
    assert all(
        evidence == first
        and result.artifact == publication.artifact
        and not result.wrote
        for evidence, result in repeats
    )
    assert inventory(tmp_path) == before


def test_concurrent_first_preparations_publish_one_bundle(tmp_path):
    f = fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = tuple(pool.map(lambda _: execute(f), range(3)))
    assert sum(publication.wrote for _, publication in outcomes) == 1
    assert len({evidence.digest for evidence, _ in outcomes}) == 1


def test_shared_originals_can_support_distinct_policies_without_reusing_record_metadata(
    tmp_path,
):
    f = fixture(tmp_path)
    first_request = f.request
    first, _ = execute(f)
    f.request = first_request.model_copy(
        update={
            "reference_policy": IssuerMarketReferencePlanPolicyV1(maximum_age_days=365),
        }
    )
    second, _ = execute(f)
    assert second.classification == first.classification
    assert second.country_mapping == first.country_mapping
    assert second.digest != first.digest and not second.issue_codes
    before = inventory(tmp_path)
    assert not execute(f)[1].wrote
    f.request = first_request
    assert not execute(f)[1].wrote
    assert inventory(tmp_path) == before


def test_changed_crosswalk_version_is_a_retained_refusal(tmp_path):
    f = fixture(tmp_path)
    execute(f)
    f.request = f.request.model_copy(
        update={
            "industry_policy": f.request.industry_policy.model_copy(
                update={"mapping_version": "unsupported"}
            ),
        }
    )
    evidence, _ = execute(f)
    assert evidence.industry_mapping.status == "refused"
    assert not evidence.release_refs and evidence.market.decision.inputs is None
    assert not execute(f)[1].wrote


def test_alternate_classification_format_is_injected_without_changing_assembly(
    tmp_path,
):
    f = fixture(tmp_path)
    provider = AlternateJsonClassificationProvider()
    original = RetainedSourceV1(
        source_id="alternate-original",
        uri="https://example.test/classification",
        source_version="alternate-json-v1",
        terms_reference="https://example.test/terms",
        captured_at=CAPTURED,
        content=canonical_bytes(
            {
                "cik": f.request.classification_request.issuer_id,
                "accession": f.request.classification_request.accession_number,
                "period_end": "2024-09-28",
                "country": "US",
                "sic": "3571",
            }
        ),
    )
    f.request = f.request.model_copy(
        update={"classification_provider_id": provider.provider_id}
    )
    f.preparation = IssuerMarketPreparation(
        classification_provider=provider,
        classification_sources=SimpleNamespace(
            retained_sources=lambda request, snapshot: (original,)
        ),
        country_provider=SecStateCountryCrosswalk(),
        industry_provider=SecSicDamodaranIndustryCrosswalk(),
        artifacts=f.artifacts,
    )
    evidence, _ = execute(f)
    assert evidence.classification.status == "matched"
    assert evidence.classification.provider_id == provider.provider_id
    # Different schemes need explicit crosswalks; they cannot inherit SEC mappings.
    assert (
        evidence.country_mapping.status == evidence.industry_mapping.status == "refused"
    )
    assert not evidence.release_refs


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"source_id": "current-company-metadata"},
            "SEC_CLASSIFICATION_SUBMISSION_MISSING",
        ),
        (
            {"form": "10-K/A", "is_amendment": True},
            "SEC_CLASSIFICATION_SUBMISSION_CONTEXT_MISMATCH",
        ),
        (
            {"available_at": AT + timedelta(days=1)},
            "SEC_CLASSIFICATION_SUBMISSION_CONTEXT_MISMATCH",
        ),
        (
            {"role": SourceRole.ACQUISITION},
            "SEC_CLASSIFICATION_SUBMISSION_CONTEXT_MISMATCH",
        ),
        (
            {"terms_reference": "invented terms"},
            "SEC_CLASSIFICATION_SUBMISSION_CONTEXT_MISMATCH",
        ),
    ],
)
def test_bad_source_context_is_retained_and_cannot_supply_market_inputs(
    tmp_path, change, code
):
    f = fixture(tmp_path)
    f.snapshot = _changed(
        f.snapshot,
        source_records=(f.snapshot.source_records[0].model_copy(update=change),),
    )
    evidence, publication = execute(f)
    assert publication.wrote and code in evidence.issue_codes
    assert evidence.market.decision.inputs is None and evidence.release_refs == ()
    assert (
        "ISSUER_CLASSIFICATION_REPRODUCTION_FAILED"
        in evidence.classification.issue_codes
    )
    assert not execute(f)[1].wrote


def test_duplicate_originals_are_retained_as_conflict(tmp_path):
    f = fixture(tmp_path)
    f.snapshot = _changed(f.snapshot, source_records=f.snapshot.source_records * 2)
    evidence, _ = execute(f)
    assert "SEC_CLASSIFICATION_SUBMISSION_AMBIGUOUS" in evidence.issue_codes
    assert not evidence.release_refs


def test_source_hash_is_rechecked_even_with_a_faulty_content_adapter(tmp_path):
    f = fixture(tmp_path)
    f.preparation = preparer(
        f.artifacts, SimpleNamespace(get=lambda *args, **kwargs: b"tampered")
    )
    evidence, _ = execute(f)
    assert "SOURCE_HASH_MISMATCH" in evidence.issue_codes
    assert evidence.market.decision.inputs is None


def test_missing_bytes_refuses_and_retains_immutable_snapshot_reference(tmp_path):
    f = fixture(tmp_path)
    for path in (tmp_path / "originals").rglob("*"):
        if path.is_file():
            path.unlink()
    evidence, _ = execute(f)
    assert "SOURCE_BYTES_UNAVAILABLE" in evidence.issue_codes
    assert evidence.snapshot_manifest_digest == f.snapshot.manifest_digest
    assert not evidence.release_refs


def test_unmapped_industry_and_missing_admissions_preserve_failures(tmp_path):
    f = fixture(tmp_path, sic="UNSUPPORTED INDUSTRY [9999]")
    evidence, _ = execute(f)
    assert evidence.industry_mapping.status == "refused"
    assert evidence.market.decision.inputs is None and not evidence.release_refs
    f = fixture(tmp_path / "missing")
    evidence, _ = execute(f, admissions=())
    assert "MARKET_REFERENCE_SOURCE_UNAVAILABLE" in evidence.issue_codes
    assert evidence.admissions == ()
    assert not execute(f, admissions=())[1].wrote


def test_edited_admissions_cannot_retain_an_approved_decision(tmp_path):
    f = fixture(tmp_path)
    evidence, _ = execute(f)
    payload = evidence.model_dump()
    payload["admissions"] = ()
    with pytest.raises(ValidationError, match="differs from its admissions"):
        IssuerMarketPreparationEvidenceV1.model_validate(payload)


def test_provider_and_request_context_are_explicit_pins(tmp_path):
    f = fixture(tmp_path)
    f.request = f.request.model_copy(
        update={"classification_provider_id": "unconfigured"}
    )
    with pytest.raises(ValueError, match="not configured"):
        execute(f)
    payload = market_request().model_dump()
    payload["classification_request"]["valuation_at"] += timedelta(days=1)
    with pytest.raises(ValidationError, match="one issuer and date"):
        IssuerMarketPreparationRequestV1.model_validate(payload)


def test_current_mode_freezes_nested_market_dates_with_the_source_plan(tmp_path):
    f = current_fixture(tmp_path)
    first = f.request.template.ingestions[0]
    proposal = market_request(
        f.request.requested_at,
        issuer_id=first.identity.issuer_id,
        accession=first.filing.accession_number,
    )
    template = SOURCE_PREPARATION_PLAN.validate_python(
        {
            **f.request.template.model_dump(),
            "issuer_market_policy": proposal,
        }
    )
    f.request = CurrentSourcePreparationRequestV1(template=template)
    selected, _ = select(f)
    assert (
        selected.plan.issuer_market_policy.classification_request.valuation_at
        == selected.plan.ingestions[0].valuation_timestamp
    )
    assert (
        selected.plan.issuer_market_policy.market_policy.terminal_growth_plan.valuation_at
        == selected.plan.ingestions[0].valuation_timestamp
    )
    assert selected.plan.issuer_market_policy == proposal.at(
        selected.plan.ingestions[0].valuation_timestamp
    )
    assert select(f)[1].wrote is False


def test_runner_retains_market_refusal_and_never_calls_composer(tmp_path, monkeypatch):
    f = _fixture(tmp_path)
    first = f.plan.ingestions[0]
    proposal = market_request(
        first.valuation_timestamp,
        issuer_id=first.identity.issuer_id,
        accession=first.filing.accession_number,
    )
    plan = SOURCE_PREPARATION_PLAN.validate_python(
        {**f.plan.model_dump(), "issuer_market_policy": proposal}
    )
    content = FilesystemContentStore(tmp_path / "unused-originals")
    runner = SourcePreparationRunner(
        application=f.application,
        metadata=f.metadata,
        acquisition=None,
        artifacts=f.artifacts,
        canary=None,
        issuer_market_preparation=preparer(f.artifacts, content),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("refused market preparation reached composer")

    monkeypatch.setattr(type(f.application), "prepare_valuation", forbidden)
    result = _run(runner, plan)
    report = _reader(f, result)
    assert report.status == "blocked" and report.calculation is None
    assert "SEC_CLASSIFICATION_SUBMISSION_MISSING" in report.issue_codes
    assert report.issuer_market_preparation_ref is not None
    evidence = IssuerMarketPreparationEvidenceV1.model_validate_json(
        f.artifacts.read(report.issuer_market_preparation_ref.artifact_id)
    )
    assert evidence.snapshot_manifest_digest == f.snapshot.manifest_digest
    before = inventory(tmp_path)
    assert not _run(runner, plan).wrote
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("candidate_requested", [False, True])
def test_prepared_market_proposal_cannot_bypass_exact_release_binding(
    tmp_path, monkeypatch, candidate_requested
):
    f = _fixture(tmp_path, released=not candidate_requested)
    first = f.plan.ingestions[0]
    proposal = market_request(
        first.valuation_timestamp,
        issuer_id=first.identity.issuer_id,
        accession=first.filing.accession_number,
    )
    plan = SOURCE_PREPARATION_PLAN.validate_python(
        {**f.plan.model_dump(), "issuer_market_policy": proposal}
    )
    original = replace(
        sec_submission(
            cik=first.identity.issuer_id, accession=first.filing.accession_number
        ),
        captured_at=first.valuation_timestamp,
    )
    stage = IssuerMarketPreparation(
        classification_provider=SecSubmissionClassificationProvider(),
        classification_sources=SimpleNamespace(
            retained_sources=lambda request, snapshot: (original,)
        ),
        country_provider=SecStateCountryCrosswalk(),
        industry_provider=SecSicDamodaranIndustryCrosswalk(),
        artifacts=f.artifacts,
    )
    admissions = _admissions(first.valuation_timestamp)
    candidate, canary = _reviewed_candidate(f) if candidate_requested else (None, None)
    runner = SourcePreparationRunner(
        application=f.application,
        metadata=f.metadata,
        acquisition=None,
        artifacts=f.artifacts,
        canary=canary,
        issuer_market_preparation=stage,
    )

    # Exercise the stage with approved source inputs; the old release lacks its exact refs.
    def prepared(plan, snapshot, outcomes):
        return stage.execute(
            plan.issuer_market_policy, snapshot=snapshot, admissions=admissions
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("unbound market proposal reached activation/composer")

    monkeypatch.setattr(runner, "_prepare_issuer_market", prepared)
    monkeypatch.setattr(runner, "_activate", forbidden)
    monkeypatch.setattr(type(f.application), "prepare_valuation", forbidden)
    report = _reader(f, _run(runner, plan, candidate=candidate))
    assert report.status == "blocked" and report.calculation is None
    assert report.issue_codes == ("ISSUER_MARKET_PREPARATION_RELEASE_MISMATCH",)
    evidence = IssuerMarketPreparationEvidenceV1.model_validate_json(
        f.artifacts.read(report.issuer_market_preparation_ref.artifact_id)
    )
    assert not evidence.issue_codes and evidence.market.decision.inputs is not None
    assert f.state.publications == 0


def test_reference_policy_default_is_canonical_before_and_after_serialization():
    policy = IssuerMarketReferencePlanPolicyV1()
    reread = IssuerMarketReferencePlanPolicyV1.model_validate_json(
        canonical_bytes(policy)
    )
    assert policy == reread and sha256_digest(policy) == sha256_digest(reread)


def test_prepared_release_refs_work_with_the_existing_deployment_policy_verifier(
    tmp_path,
):
    f = fixture(tmp_path)
    evidence, _ = execute(f)
    base, _, policy, _, _, _ = _bound()
    payload = base.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (
        tuple(
            ref
            for ref in base.artifact_refs
            if ref.role not in {item.role for item in evidence.release_refs}
        )
        + evidence.release_refs
    )
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    payload = policy.model_dump(exclude={"policy_digest"})
    payload["market_inputs"] = evidence.market.decision.inputs
    payload["source_refs"] = (
        AUTOMATIC_MARKET_POLICY_REF_PREFIX + sha256_digest(evidence.market),
        sha256_digest(evidence.market.plan_decision.plan),
        sha256_digest(evidence.request.market_policy.terminal_growth_plan),
    )
    approved_policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    assert (
        load_release_automatic_market_policy(
            manifest,
            snapshot=f.snapshot,
            policy=approved_policy,
            admissions=evidence.admissions,
            artifacts=f.artifacts,
            expected_source_revision=REVISION,
        )
        == evidence.market
    )


def test_postgres_repeat_reopen_and_empty_store_restore_reuse_market_evidence(
    tmp_path, recovery_databases
):
    f = fixture(tmp_path / "inputs")
    source_url, target_url = recovery_databases
    content_root = tmp_path / "persistent"

    def wire(store, root):
        content = PostgresContentStore(root, store)
        artifacts = PostgresArtifactStore(store, content)
        return content, artifacts, preparer(artifacts, content)

    store = PostgresMetadataStore(source_url, auto_migrate=True)
    store.start()
    try:
        content, artifacts, stage = wire(store, content_root)
        content.put(f.original.content, media_type="text/plain")
        store.publish_snapshot(f.snapshot)
        evidence, receipt = stage.execute(
            f.request, snapshot=f.snapshot, admissions=_admissions(AT)
        )
        assert receipt.wrote and not evidence.issue_codes
        before = inventory(content_root)
        assert not stage.execute(
            f.request, snapshot=f.snapshot, admissions=_admissions(AT)
        )[1].wrote
        assert inventory(content_root) == before
    finally:
        store.close()

    reopened = PostgresMetadataStore(source_url)
    reopened.start()
    try:
        _, artifacts, stage = wire(reopened, content_root)
        result, repeated = stage.execute(
            f.request,
            snapshot=reopened.get_snapshot(f.snapshot.snapshot_id),
            admissions=_admissions(AT),
        )
        assert result == evidence and repeated == receipt.model_copy(
            update={"wrote": False}
        )
        assert artifacts.read(repeated.artifact.artifact_id) == canonical_bytes(
            evidence
        )
        assert inventory(content_root) == before
    finally:
        reopened.close()

    backup = asyncio.run(
        export_backup(
            source_url, content_root, tmp_path / "backup", source_revision=REVISION
        )
    )
    restored_root = tmp_path / "restored"
    asyncio.run(
        restore_backup(
            target_url,
            restored_root,
            tmp_path / "backup" / backup.manifest_digest,
            manifest_digest=backup.manifest_digest,
        )
    )
    restored = PostgresMetadataStore(target_url)
    restored.start()
    try:
        _, artifacts, stage = wire(restored, restored_root)
        restored_before = inventory(restored_root)
        result, repeated = stage.execute(
            f.request,
            snapshot=restored.get_snapshot(f.snapshot.snapshot_id),
            admissions=_admissions(AT),
        )
        assert result == evidence and repeated == receipt.model_copy(
            update={"wrote": False}
        )
        assert artifacts.read(repeated.artifact.artifact_id) == canonical_bytes(
            evidence
        )
        assert inventory(restored_root) == restored_before
    finally:
        restored.close()
