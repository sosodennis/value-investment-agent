"""Compile retained source identities without implying complete source coverage."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest

from fundamental_service.automatic_data_release import AutomaticDataReleasePolicyV1
from fundamental_service.automatic_release_evidence import (
    require_automatic_release_sources,
)
from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.preparation_release import assemble_preparation_release
from fundamental_service.preparation_release import select_preparation_release_facts
from fundamental_service.serialization import canonical_bytes
from test_automatic_source_acquisition import acquisition_case, acquire
from test_automatic_source_preparation import automatic_plan
from test_issuer_operating_release import inventory


def assembly_case(tmp_path, monkeypatch):
    request, acquisition, _, metadata, artifacts = acquisition_case(
        tmp_path, monkeypatch
    )
    facts = []
    publish = metadata.publish_sec_ingestion

    def retain(**value):
        facts.extend(value["facts"])
        return publish(**value)

    metadata.publish_sec_ingestion = retain
    acquired = acquire(request, acquisition)
    snapshot = metadata.snapshots[acquired.snapshot_id]
    plan = automatic_plan(request)
    batch = artifacts.get(acquired.mapping_evidence_ref)
    policy = AutomaticDataReleasePolicyV1(
        profile_id=plan.release_profile_id,
        scope="security",
        model_id=plan.model_id,
        model_version=request.model_version,
        mapping_version=request.mapping_version,
        requirements_profile_digest=plan.requirements_profile.digest,
        parser_version=snapshot.parser_version,
        quality_profile_digest="1" * 64,
        validation_profile_digest=snapshot.validation_profile_digest,
        verifier_id="synthetic-machine",
        workflow_identity="synthetic/automatic",
    )
    return (
        dict(
            plan=plan,
            snapshot=snapshot,
            facts=tuple(facts),
            mappings=tuple(metadata.mappings.values()),
            batch_refs=(
                ArtifactRefV1(
                    artifact_id=batch.artifact_id,
                    content_hash=batch.content_hash,
                    media_type=batch.media_type,
                    role="automatic-mapping-batch-decision-v1",
                ),
            ),
            artifacts=artifacts,
            policy=policy,
            working_capital_policy=None,
            conditional_capital_policy=None,
            prepared_refs=(),
        ),
        acquisition,
        acquired,
    )


def test_assembly_reuses_exact_originals_approvals_taxonomy_and_observed_facts(
    tmp_path, monkeypatch
):
    options, acquisition, acquired = assembly_case(tmp_path, monkeypatch)
    request = assemble_preparation_release(**options)
    assert acquired.quality_status is QualityStatus.ABSTAIN
    assert options["snapshot"].coverage_status is QualityStatus.VERIFIED
    assert "non_operating_assets" in acquired.missing_evidence
    assert (
        request.manifest.required_fields
        == options["plan"].requirements_profile.required_fact_fields
    )
    assert {item.fact_id for item in request.manifest.snapshot_refs[0].facts} == {
        item.fact_id for item in options["facts"]
    }
    assert request.manifest.taxonomy_refs
    assert request.content.mapping_reviews
    # Regulatory source coverage is distinct from complete numerical eligibility.
    assert require_automatic_release_sources(
        request.manifest,
        request.content,
        snapshots=SimpleNamespace(get=lambda _: options["snapshot"]),
        mappings=SimpleNamespace(
            get_mapping={
                item.decision_id: item for item in options["mappings"]
            }.__getitem__
        ),
        artifacts=options["artifacts"],
        validation_profile_digest=options["policy"].validation_profile_digest,
    )
    assert not hasattr(request, "verification")
    assert not hasattr(request, "caller_approval")
    before = inventory(options["artifacts"].root)
    with ThreadPoolExecutor(max_workers=3) as pool:
        repeats = tuple(
            pool.map(lambda _: assemble_preparation_release(**options), range(3))
        )
    assert all(canonical_bytes(item) == canonical_bytes(request) for item in repeats)
    assert before == inventory(options["artifacts"].root)
    assert acquire(options["plan"].ingestions[0], acquisition).reused


@pytest.mark.parametrize(
    "change", ("batch_hash", "missing_batch", "mapping_set", "plan_revision")
)
def test_assembly_rejects_missing_conflicting_or_wrong_plan_evidence(
    tmp_path, monkeypatch, change
):
    options, _, _ = assembly_case(tmp_path, monkeypatch)
    if change == "batch_hash":
        options["batch_refs"] = (
            options["batch_refs"][0].model_copy(update={"content_hash": "0" * 64}),
        )
    elif change == "missing_batch":
        options["batch_refs"] = ()
    elif change == "mapping_set":
        options["mappings"] = options["mappings"][:-1]
    else:
        plan = options["plan"]
        options["plan"] = plan.model_copy(
            update={
                "source_revision": "b" * 40,
                "ingestions": tuple(
                    item.model_copy(update={"source_revision": "b" * 40})
                    for item in plan.ingestions
                ),
            }
        )
    with pytest.raises(DataReleaseError):
        assemble_preparation_release(**options)


def test_overlapping_original_periods_use_the_existing_pit_selector(
    tmp_path, monkeypatch
):
    options, _, _ = assembly_case(tmp_path, monkeypatch)
    fact = next(
        fact
        for fact in options["facts"]
        if fact.normalized_field == "stock_based_compensation"
    )
    source = next(
        source
        for source in options["snapshot"].source_records
        if source.content_hash == fact.source.content_hash
    )
    older_source = source.model_copy(
        update={
            "content_hash": "e" * 64,
            "available_at": source.available_at - timedelta(days=1),
            "accession_number": "0000000001-25-000001",
        }
    )
    older = fact.model_copy(
        update={
            "fact_id": fact.fact_id + "-older",
            "available_at": fact.available_at - timedelta(days=1),
            "accession_number": older_source.accession_number,
            "source": fact.source.model_copy(
                update={"content_hash": older_source.content_hash}
            ),
        }
    )
    snapshot = options["snapshot"].model_copy(
        update={"source_records": (*options["snapshot"].source_records, older_source)}
    )
    selected, decisions = select_preparation_release_facts((older, fact), snapshot)
    assert selected == (fact,)
    assert older.fact_id in decisions[0].rejected_candidates
    assert (
        decisions[0].rejected_candidate_reasons[0].reason
        == "superseded_by_later_available_filing"
    )


@pytest.mark.parametrize("interrupted", (False, True))
def test_automatic_runner_reuses_active_release_and_retains_pre_activation_sources(
    tmp_path, monkeypatch, interrupted
):
    """A fake mapping/signing boundary isolates real serving/composer orchestration."""
    from fundamental_service.automatic_source_mapping import (
        AutomaticSecIngestionRequestV1,
    )
    from fundamental_service.contracts import CallerApprovalEnvelopeV1
    from fundamental_service.preparation_runner import SourcePreparationRunner
    from fundamental_service.source_plan_contracts import (
        AutomaticSourcePreparationPlanV1,
    )
    from fundamental_service.snapshots import SnapshotError
    from fundamental_service.automatic_mapping import automatic_mapping_policy_digest
    from test_preparation_runner import (
        _fixture,
        _reviewed_candidate,
        _acquisition,
        _run,
        _reader,
        VALUATION_TIME,
    )

    fixture = _fixture(tmp_path, released=False)
    original = fixture.plan.ingestions[0]
    candidate, canary = _reviewed_candidate(fixture)
    payload = original.model_dump(exclude={"mappings"})
    payload.update(
        filing={
            "accession_number": next(
                source.accession_number
                for source in fixture.snapshot.source_records
                if source.accession_number
            ),
            "forms": ("10-K",),
        },
        identity_basis="original-filing-dei-v1",
        supplemental_filing_policy="sec-equity-award-proxy.v2",
        source_revision=fixture.plan.source_revision,
        evaluator_id="synthetic-evaluator",
        mapping_policy_digest=automatic_mapping_policy_digest(),
        mapping_version="mapping-v1",
        model_id=fixture.plan.model_id,
        model_version="fcff_dcf-v2",
        requirements_digest=fixture.plan.requirements_profile.digest,
        required_fields=fixture.plan.requirements_profile.required_fact_fields,
    )
    request = AutomaticSecIngestionRequestV1.model_validate(payload)
    plan = AutomaticSourcePreparationPlanV1(
        source_revision=fixture.plan.source_revision,
        release_profile_id=fixture.plan.release_profile_id,
        model_id=fixture.plan.model_id,
        ingestions=(request,),
    )
    acquisition = _acquisition(fixture)
    acquisition.retained_acquisition = lambda _: None
    runner = SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=acquisition,
        artifacts=fixture.artifacts,
        canary=canary,
        automatic_release=SimpleNamespace(),
        automatic_release_policy=SimpleNamespace(),
    )
    monkeypatch.setattr(runner, "_plan_mappings", lambda _: (original.mappings,))
    calls = []

    def compiled(plan_arg, snapshot, outcomes, admissions):
        assert runner._retained_outcomes(plan_arg) == outcomes
        calls.append(plan_arg.digest)
        publication = fixture.artifacts.put_with_receipt(
            "synthetic-auto-decision", {"synthetic": True}
        )
        ref = ArtifactRefV1(
            artifact_id=publication.artifact.artifact_id,
            content_hash=publication.artifact.content_hash,
            media_type=publication.artifact.media_type,
            role="automatic-release-decision-v1",
        )
        return candidate, ref, ()

    monkeypatch.setattr(runner, "_automatic_candidate", compiled)
    persist = runner._persist
    if interrupted:

        def stopped(*args):
            assert fixture.state.active is not None
            raise SnapshotError(
                "SYNTHETIC_INTERRUPTION", "after activation before flow report"
            )

        monkeypatch.setattr(runner, "_persist", stopped)
        with pytest.raises(SnapshotError, match="after activation"):
            _run(runner, plan)
        monkeypatch.setattr(runner, "_persist", persist)
    first = _run(runner, plan)
    report = _reader(fixture, first)
    assert report.status == "approval_required" and report.calculation is None
    assert len(report.source_outcomes) == 1 and report.automatic_release_ref is None
    second = _run(runner, plan)
    assert second.artifact == first.artifact and not second.wrote
    assert len(calls) == 1 and len(acquisition.calls) == 1
    assert fixture.state.publications == 1
    approval = CallerApprovalEnvelopeV1(
        input_digest=report.preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    calculated = _reader(fixture, _run(runner, plan, approval=approval))
    assert (
        calculated.status == "calculated"
        and calculated.calculation.base.per_share_value > 0
    )


def test_assembly_failure_report_does_not_repeat_the_failed_market_adapter(
    tmp_path, monkeypatch
):
    from fundamental_service.preparation_runner import (
        SourcePreparationRunner,
        SourcePreparationEvidenceV1,
    )
    from fundamental_service.source_plan_contracts import SOURCE_PREPARATION_PLAN
    from test_issuer_market_preparation import market_request
    from test_preparation_runner import _fixture

    fixture = _fixture(tmp_path)
    first = fixture.plan.ingestions[0]
    plan = SOURCE_PREPARATION_PLAN.validate_python(
        {
            **fixture.plan.model_dump(),
            "issuer_market_policy": market_request(
                first.valuation_timestamp,
                issuer_id=first.identity.issuer_id,
                accession=first.filing.accession_number,
            ),
        }
    )
    failure = fixture.artifacts.put_with_receipt(
        "synthetic-failed-market",
        {
            "code": "AUTOMATIC_PREPARATION_EVIDENCE_INVALID",
            "message": "classification provider differs from deployed provider",
        },
    )
    failure_ref = ArtifactRefV1(
        artifact_id=failure.artifact.artifact_id,
        content_hash=failure.artifact.content_hash,
        media_type=failure.artifact.media_type,
        role="automatic-release-assembly-failure-v1",
    )
    runner = SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=None,
        artifacts=fixture.artifacts,
        canary=None,
    )

    def forbidden(*args, **kwargs):
        pytest.fail("blocked persistence repeated the failed adapter")

    monkeypatch.setattr(runner, "_prepare_issuer_market", forbidden)
    evidence = SourcePreparationEvidenceV1(
        source_revision=plan.source_revision,
        plan_digest=plan.digest,
        status="blocked",
        snapshot_id=fixture.snapshot.snapshot_id,
        snapshot_manifest_digest=fixture.snapshot.manifest_digest,
        issue_codes=("AUTOMATIC_PREPARATION_EVIDENCE_INVALID",),
        automatic_release_ref=failure_ref,
    )
    publication = runner._persist(plan, evidence)
    retained = SourcePreparationEvidenceV1.model_validate_json(
        fixture.artifacts.read(publication.artifact.artifact_id)
    )
    assert (
        retained.status == "blocked" and retained.automatic_release_ref == failure_ref
    )
    assert failure_ref.content_hash in publication.artifact.dependency_hashes
    assert not runner._persist(plan, evidence).wrote
