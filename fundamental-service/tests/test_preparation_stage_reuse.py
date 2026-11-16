"""Preparation stage reuse preserves release matching and current-data refusals."""

from types import SimpleNamespace

import pytest

from fundamental_service.facts import FilesystemCanonicalFactRepository
from fundamental_service.operations import ServiceError
from fundamental_service.preparation_release import assemble_preparation_release
from fundamental_service.preparation_runner import SourcePreparationRunner
from fundamental_service.snapshots import SnapshotError
from test_conditional_capital_preparation import recipe as capital_recipe
from test_conditional_reinvestment_composer import _fixture as conditional_fixture
from test_composite_source_preparation import _plan
from test_preparation_release import assembly_case
from test_preparation_runner import _fixture, _reviewed_candidate, _runner
from test_valuation_release_inputs import _client


def release_case(tmp_path, conditional):
    if conditional:
        fixture = conditional_fixture(tmp_path, sec_profile=True)
        plan = _plan(
            fixture,
            conditional_capital_recipe=capital_recipe(fixture.capital_policy),
            conditional_reinvestment_recipe=fixture.forward_policy.recipe,
        )
        fixture.application = _client(fixture).app.state.application
    else:
        fixture = _fixture(tmp_path)
        plan = fixture.plan
    candidate, _ = _reviewed_candidate(fixture)
    return fixture, plan, candidate


@pytest.mark.parametrize("conditional", (False, True))
def test_release_and_candidate_consume_the_same_checked_stage(
    tmp_path, monkeypatch, conditional
):
    fixture, plan, candidate = release_case(tmp_path, conditional)
    runner = _runner(fixture)
    prepared = runner._prepare_plan_facts(plan, fixture.snapshot)
    expected = runner._matches_release(plan, fixture.snapshot, candidate.manifest)
    assert expected

    def repeated(*args, **kwargs):
        pytest.fail("release matching must consume the checked stage output")

    monkeypatch.setattr(runner, "_prepare_plan_facts", repeated)
    monkeypatch.setattr(runner, "_plan_mappings", repeated)
    monkeypatch.setattr(runner, "_plan_facts", repeated)
    assert (
        runner._matches_release(
            plan, fixture.snapshot, candidate.manifest, prepared_facts=prepared
        )
        == expected
    )
    assert (
        runner._candidate_snapshot(plan, candidate, prepared_facts=prepared)
        == fixture.snapshot
    )
    runner.validate_candidate(plan, candidate, prepared_facts=prepared)


@pytest.mark.parametrize("fault", ("mapping", "fact"))
def test_prepared_stage_does_not_mask_changed_released_data(tmp_path, fault):
    fixture, plan, candidate = release_case(tmp_path, False)
    runner = _runner(fixture)
    prepared = runner._prepare_plan_facts(plan, fixture.snapshot)
    if fault == "mapping":
        key = candidate.manifest.mapping_refs[0].mapping_id
        fixture.mappings[key] = fixture.mappings[key].model_copy(
            update={"mapping_version": "changed-version"}
        )
    else:
        fact_id = candidate.manifest.snapshot_refs[0].facts[0].fact_id
        fact = fixture.facts.get(fact_id)
        (fixture.facts.root / (fact_id + ".json")).write_text(
            fact.model_copy(update={"value": fact.value + 1}).model_dump_json()
        )
    with pytest.raises(ServiceError) as caught:
        runner._matches_release(
            plan, fixture.snapshot, candidate.manifest, prepared_facts=prepared
        )
    assert caught.value.code == f"DATA_RELEASE_{fault.upper()}_MISMATCH"


def test_unacquired_new_plan_is_a_release_miss_not_a_preparation_failure(
    tmp_path, monkeypatch
):
    options, acquisition, _ = assembly_case(tmp_path, monkeypatch)
    manifest = assemble_preparation_release(**options).manifest
    facts = FilesystemCanonicalFactRepository(tmp_path / "release-facts")
    for fact in options["facts"]:
        facts.publish(fact)
    runner = SourcePreparationRunner(
        application=SimpleNamespace(
            fact_repository=facts,
            artifact_store=options["artifacts"],
            snapshot=lambda _: options["snapshot"],
        ),
        metadata=acquisition.metadata,
        acquisition=acquisition,
        artifacts=options["artifacts"],
        canary=None,
    )
    monkeypatch.setattr(acquisition, "retained_acquisition", lambda _: None)
    assert not runner._matches_release(options["plan"], options["snapshot"], manifest)


def test_release_matching_propagates_nonmissing_source_failures(tmp_path, monkeypatch):
    fixture, plan, candidate = release_case(tmp_path, False)
    runner = _runner(fixture)

    def corrupt(*args, **kwargs):
        raise SnapshotError("ARTIFACT_HASH_MISMATCH", "changed source")

    monkeypatch.setattr(runner, "_prepare_plan_facts", corrupt)
    with pytest.raises(SnapshotError, match="changed source"):
        runner._matches_release(plan, fixture.snapshot, candidate.manifest)


def test_release_reuse_rejects_a_stage_from_another_plan(tmp_path):
    fixture, plan, candidate = release_case(tmp_path, False)
    runner = _runner(fixture)
    prepared = runner._prepare_plan_facts(plan, fixture.snapshot)
    changed = plan.model_copy(update={"source_revision": "f" * 40})
    with pytest.raises(ValueError, match="exact plan and snapshot"):
        runner._matches_release(
            changed, fixture.snapshot, candidate.manifest, prepared_facts=prepared
        )
