"""Compile retained source identities without implying complete source coverage."""

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from fundamental_service.automatic_data_release import AutomaticDataReleasePolicyV1
from fundamental_service.automatic_mapping_batch import AutomaticMappingBatchRequestV1
from fundamental_service.automatic_release_evidence import (
    require_automatic_release_sources,
)
from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.facts import (
    FilesystemCanonicalFactRepository,
    canonical_fact_digest,
)
from fundamental_service.mapping_input_storage import resolve_mapping_input
from fundamental_service.preparation_release import assemble_preparation_release
from fundamental_service.preparation_release import select_preparation_release_facts
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_source_acquisition import acquisition_case, acquire
from test_automatic_source_preparation import automatic_plan
from test_issuer_operating_release import inventory


def assembly_case(tmp_path, monkeypatch, **acquisition_options):
    request, acquisition, _, metadata, artifacts = acquisition_case(
        tmp_path, monkeypatch, **acquisition_options
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


def test_regulatory_coverage_does_not_require_a_selected_mapping_from_every_original(
    tmp_path, monkeypatch
):
    options, _, _ = assembly_case(tmp_path, monkeypatch)
    request = assemble_preparation_release(**options)
    # Isolate original coverage after all its observations are superseded.
    # Numerical content still requires the approvals for every selected fact.
    content = request.content.model_copy(update={"mapping_reviews": ()})
    assert require_automatic_release_sources(
        request.manifest,
        content,
        snapshots=SimpleNamespace(get=lambda _: options["snapshot"]),
        mappings=SimpleNamespace(get_mapping=lambda _: pytest.fail("unused mapping")),
        artifacts=options["artifacts"],
        validation_profile_digest=options["policy"].validation_profile_digest,
    )


@pytest.mark.parametrize("tamper", (False, True))
def test_approved_observations_replay_despite_other_missing_mapping_roles(
    tmp_path, monkeypatch, tamper
):
    """Validate an expense-only source release, without claiming valuation coverage."""
    options, acquisition, acquired = assembly_case(tmp_path, monkeypatch)
    request = assemble_preparation_release(**options)
    assert "MAPPING_AUTOMATIC_RULE_UNSUPPORTED" in acquired.issue_codes
    assert acquired.missing_evidence
    facts = tuple(
        fact
        for fact in options["facts"]
        if fact.normalized_field == "stock_based_compensation"
    )
    assert facts
    repository = FilesystemCanonicalFactRepository(tmp_path / "released-facts")
    for fact in facts:
        if tamper:
            fact = fact.model_copy(update={"issue_codes": ("UNREPRODUCED_DIAGNOSTIC",)})
        repository.publish(fact)
    mapping_ids = {fact.mapping_decision_id for fact in facts}
    references = tuple(
        ref.model_copy(
            update={"fact_digest": canonical_fact_digest(repository.get(ref.fact_id))}
        )
        for ref in request.manifest.snapshot_refs[0].facts
        if ref.fact_id in {fact.fact_id for fact in facts}
    )
    payload = request.manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        required_fields=("stock_based_compensation",),
        mapping_refs=tuple(
            ref
            for ref in request.manifest.mapping_refs
            if ref.mapping_id in mapping_ids
        ),
        snapshot_refs=(
            request.manifest.snapshot_refs[0].model_copy(
                update={
                    "facts": references,
                    "fact_set_digest": sha256_digest(references),
                }
            ),
        ),
    )
    manifest = type(request.manifest)(**payload, manifest_digest=sha256_digest(payload))
    content = request.content.model_copy(
        update={
            "mapping_reviews": tuple(
                review
                for review in request.content.mapping_reviews
                if review.mapping_id in mapping_ids
            )
        }
    )
    mappings = {item.decision_id: item for item in options["mappings"]}
    runner = DataReleaseCanaryRunner(
        snapshot_repository=SimpleNamespace(get=lambda _: options["snapshot"]),
        fact_repository=repository,
        mapping_reader=SimpleNamespace(get_mapping=mappings.__getitem__),
        artifact_reader=options["artifacts"],
        trust_roots=acquisition.automatic_mapping_authority.trust_roots,
    )
    if not tamper:
        checked = runner.validate_content(manifest, content)
        assert checked.checked_fact_digests == tuple(
            sorted(canonical_fact_digest(fact) for fact in facts)
        )
    else:
        with pytest.raises(DataReleaseError) as error:
            runner.validate_content(manifest, content)
        assert error.value.code == "DATA_RELEASE_MAPPING_OBSERVATION_MISMATCH"


def test_two_original_assembly_keeps_coverage_after_pit_prunes_older_mappings(
    tmp_path, monkeypatch
):
    import test_automatic_source_acquisition as acquisition_fixtures

    from fundamental_service.history_composition import compose_original_history
    from fundamental_service.original_issuer import evaluate_original_issuer
    from fundamental_service.snapshots import FilesystemSnapshotRepository

    latest, acquisition, _ = assembly_case(tmp_path / "latest", monkeypatch)
    source_case = acquisition_fixtures.source_case

    def earlier_source_case(path):
        request, authority, validated, artifacts, mappings = source_case(path)
        original = validated.original
        accession = original.source.accession_number[:-6] + "000000"
        source = original.source.model_copy(
            update={
                "accession_number": accession,
                "uri": original.source.uri.replace(
                    original.source.accession_number.replace("-", ""),
                    accession.replace("-", ""),
                ),
                "available_at": original.source.available_at - timedelta(days=1),
            }
        )
        original = evaluate_original_issuer(
            original.report, source=source, decision_at=original.decision_at
        )
        request = request.model_copy(
            update={
                "filing": request.filing.model_copy(
                    update={"accession_number": accession}
                )
            }
        )
        return (
            request,
            authority,
            replace(validated, original=original),
            artifacts,
            mappings,
        )

    monkeypatch.setattr(acquisition_fixtures, "source_case", earlier_source_case)
    earlier, _, _ = assembly_case(
        tmp_path / "earlier",
        monkeypatch,
        metadata=acquisition.metadata,
        artifacts=latest["artifacts"],
        content=acquisition.content_store,
    )
    repository = FilesystemSnapshotRepository(tmp_path / "history")
    for options in (earlier, latest):
        repository.publish(options["snapshot"])
    snapshot = compose_original_history(
        repository,
        (earlier["snapshot"].snapshot_id, latest["snapshot"].snapshot_id),
        valuation_timestamp=latest["snapshot"].valuation_timestamp,
        fiscal_period_selector=latest["snapshot"].fiscal_period_selector,
    )
    plan = latest["plan"].model_copy(
        update={"ingestions": (*earlier["plan"].ingestions, *latest["plan"].ingestions)}
    )
    request = assemble_preparation_release(
        **{
            **latest,
            "plan": type(plan).model_validate(plan.model_dump()),
            "snapshot": snapshot,
            "facts": (*earlier["facts"], *latest["facts"]),
            "mappings": earlier["mappings"],
            "batch_refs": (*earlier["batch_refs"], *latest["batch_refs"]),
        }
    )
    assert earlier["facts"] and latest["facts"]
    assert {ref.fact_id for ref in request.manifest.snapshot_refs[0].facts} == {
        fact.fact_id for fact in latest["facts"]
    }
    selected_mappings = {item.decision_id for item in latest["mappings"]}
    assert {
        ref.mapping_id for ref in request.manifest.mapping_refs
    } == selected_mappings
    assert {
        review.mapping_id for review in request.content.mapping_reviews
    } == selected_mappings
    pruned_mappings = {
        item.decision_id for item in earlier["mappings"]
    } - selected_mappings
    assert pruned_mappings
    mappings = {item.decision_id: item for item in earlier["mappings"]}
    evidence = require_automatic_release_sources(
        request.manifest,
        request.content,
        snapshots=repository,
        mappings=SimpleNamespace(get_mapping=mappings.__getitem__),
        artifacts=latest["artifacts"],
        validation_profile_digest=latest["policy"].validation_profile_digest,
    )
    assert len(evidence) == 2
    # The unused original remains required even though none of its mappings do.
    retained = tuple(
        ref
        for ref in request.content.evidence_refs
        if ref.role != "automatic-mapping-batch-input-v1"
        or resolve_mapping_input(
            latest["artifacts"].read(ref.artifact_id),
            AutomaticMappingBatchRequestV1,
            artifacts=latest["artifacts"],
        ).original.source.accession_number
        == latest["plan"].ingestions[0].filing.accession_number
    )
    with pytest.raises(DataReleaseError) as failure:
        require_automatic_release_sources(
            request.manifest,
            request.content.model_copy(update={"evidence_refs": retained}),
            snapshots=repository,
            mappings=SimpleNamespace(get_mapping=mappings.__getitem__),
            artifacts=latest["artifacts"],
            validation_profile_digest=latest["policy"].validation_profile_digest,
        )
    assert failure.value.code == "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING"


@pytest.mark.parametrize(
    "defect,code",
    [
        ("missing_input", "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING"),
        ("input_hash", "AUTOMATIC_RELEASE_ORIGINAL_ARTIFACT_MISMATCH"),
        ("revision", "AUTOMATIC_RELEASE_ORIGINAL_EVIDENCE_MISMATCH"),
        ("closure", "AUTOMATIC_RELEASE_ORIGINAL_EVIDENCE_MISMATCH"),
        ("raw_bytes", "AUTOMATIC_RELEASE_ORIGINAL_ARTIFACT_MISMATCH"),
        ("profile", "AUTOMATIC_RELEASE_SOURCE_PROFILE_MISMATCH"),
        ("future", "AUTOMATIC_RELEASE_SOURCE_PROFILE_MISMATCH"),
        ("issuer", "AUTOMATIC_RELEASE_SOURCE_PROFILE_MISMATCH"),
        ("ambiguous", "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING"),
    ],
)
def test_retained_original_coverage_refuses_invalid_evidence_without_used_mapping(
    tmp_path, monkeypatch, defect, code
):
    from fundamental_service.original_issuer import evaluate_original_issuer

    options, _, _ = assembly_case(tmp_path, monkeypatch)
    request = assemble_preparation_release(**options)
    content = request.content.model_copy(update={"mapping_reviews": ()})
    refs = content.evidence_refs
    batch_ref = next(
        ref for ref in refs if ref.role == "automatic-mapping-batch-input-v1"
    )
    store = options["artifacts"]
    batch = resolve_mapping_input(
        store.read(batch_ref.artifact_id),
        AutomaticMappingBatchRequestV1,
        artifacts=store,
    )
    snapshot = options["snapshot"]
    profile = options["policy"].validation_profile_digest
    if defect == "missing_input":
        refs = tuple(ref for ref in refs if ref != batch_ref)
    elif defect == "input_hash":
        refs = tuple(
            ref.model_copy(update={"content_hash": "0" * 64})
            if ref == batch_ref
            else ref
            for ref in refs
        )
    elif defect in {"revision", "ambiguous"}:
        if defect == "revision":
            changed = batch.model_copy(update={"source_revision": "b" * 40})
        else:
            original = batch.original
            changed = batch.model_copy(
                update={
                    "original": evaluate_original_issuer(
                        original.report,
                        source=original.source,
                        decision_at=original.decision_at + timedelta(seconds=1),
                    )
                }
            )
        publication = store.put_with_receipt("changed-original-input", changed)
        changed_ref = batch_ref.model_copy(
            update={
                "artifact_id": publication.artifact.artifact_id,
                "content_hash": publication.artifact.content_hash,
            }
        )
        refs = (
            (*refs, changed_ref)
            if defect == "ambiguous"
            else tuple(changed_ref if ref == batch_ref else ref for ref in refs)
        )
    elif defect == "closure":
        refs = tuple(ref for ref in refs if ref != batch.evidence_refs[0])
    elif defect == "raw_bytes":
        raw_ref = next(
            ref
            for ref in batch.evidence_refs
            if ref.content_hash == batch.integrity.raw_content_hash
        )
        store = SimpleNamespace(
            get=options["artifacts"].get,
            read=lambda artifact_id: b"corrupted"
            if artifact_id == raw_ref.artifact_id
            else options["artifacts"].read(artifact_id),
        )
    elif defect == "profile":
        profile = "0" * 64
    elif defect == "future":
        snapshot = snapshot.model_copy(
            update={
                "valuation_timestamp": batch.original.source.available_at
                - timedelta(seconds=1)
            }
        )
    elif defect == "issuer":
        snapshot = snapshot.model_copy(
            update={
                "identity": snapshot.identity.model_copy(
                    update={"issuer_id": "0000000002"}
                )
            }
        )
    content = content.model_copy(update={"evidence_refs": refs})
    with pytest.raises(DataReleaseError) as failure:
        require_automatic_release_sources(
            request.manifest,
            content,
            snapshots=SimpleNamespace(get=lambda _: snapshot),
            mappings=SimpleNamespace(
                get_mapping=lambda _: pytest.fail("unused mapping")
            ),
            artifacts=store,
            validation_profile_digest=profile,
        )
    assert failure.value.code == code


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
    completed = []
    execute = acquisition.execute

    def capture(request, **kwargs):
        result = execute(request, **kwargs).model_copy(
            update={
                "canonical_fact_ids": tuple(
                    fact.fact_id for fact in fixture.facts.list()
                )
            }
        )
        completed.append(result)
        return result

    acquisition.execute = capture
    acquisition.evidence_operation = nullcontext
    acquisition.verify_original_boundary = lambda: None
    acquisition.retained_acquisition = lambda _: completed[-1] if completed else None
    runner = SourcePreparationRunner(
        application=fixture.application,
        metadata=fixture.metadata,
        acquisition=acquisition,
        artifacts=fixture.artifacts,
        canary=canary,
        automatic_release=SimpleNamespace(),
        automatic_release_policy=SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner, "_plan_mappings", lambda _, **kwargs: (original.mappings,)
    )
    calls = []

    def compiled(
        plan_arg, snapshot, outcomes, admissions, *, prepared_facts, deadline_at
    ):
        prepared_facts.require_scope(plan_arg, snapshot)
        assert prepared_facts.mapping_groups == (original.mappings,)
        assert prepared_facts.facts
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

        def stopped(plan_arg, evidence, *, prepared_facts):
            assert fixture.state.active is not None
            assert prepared_facts is not None
            prepared_facts.require_scope(
                plan_arg, fixture.application.snapshot(evidence.snapshot_id)
            )
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
    assert report.fact_evidence_inventory is not None
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


@pytest.mark.parametrize("revoke_at", ("canary", "publication"))
def test_consumed_original_revocation_prevents_the_next_release_side_effect(
    tmp_path, monkeypatch, revoke_at
):
    from datetime import UTC, datetime

    from fundamental_service.operations import ServiceError
    from fundamental_service.snapshots import SnapshotError
    from test_automatic_source_preparation import runner_case
    from test_original_preparation import case, execute

    original = case(tmp_path / "original", monkeypatch)
    prepared, _ = execute(original)
    plan, runner, _, _, _ = runner_case(tmp_path / "release", monkeypatch)
    effects = []

    def revoke():
        original.artifacts.invalidate(original.request.annual.artifact_id)

    def canary(*_):
        if revoke_at == "canary":
            revoke()

    def publish(*_):
        effects.append("published")
        if revoke_at == "publication":
            revoke()

    def inactive(_):
        raise ServiceError(
            "DATA_RELEASE_NOT_ACTIVE", "empty", status_code=404, retryable=False
        )

    runner._application = SimpleNamespace(
        config=SimpleNamespace(
            release_publish_authorized_organizations={"org"},
            release_activation_authorized_organizations={"org"},
        ),
        active_data_release=inactive,
        publish_data_release_candidate=publish,
        change_active_data_release=lambda *a, **kw: effects.append("activated"),
    )
    runner._acquisition = original.acquisition
    runner._canary = SimpleNamespace(validate=canary)
    monkeypatch.setattr(runner, "_candidate_snapshot_available", lambda *a, **kw: True)
    candidate = SimpleNamespace(
        manifest=SimpleNamespace(profile_id="profile", manifest_digest="a" * 64),
        verification=object(),
    )
    with pytest.raises(SnapshotError, match="metadata changed"):
        with original.acquisition.evidence_operation():
            original.acquisition._original_reads.get().read(prepared.artifact_id)
            runner._activate(
                candidate,
                actor_id="caller",
                organization_id="org",
                correlation_id="revocation",
                plan=plan,
                deadline_at=datetime.now(UTC) + timedelta(minutes=1),
            )
    assert effects == ([] if revoke_at == "canary" else ["published"])
    assert original.acquisition._original_reads.get() is None
