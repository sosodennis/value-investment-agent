"""Distinct plans retain distinct binding dependencies over reusable content."""

import pytest

from test_conditional_capital_preparation import recipe as capital_recipe
from test_conditional_reinvestment_composer import _fixture as forward_fixture
from test_composite_source_preparation import _plan
from test_issuer_operating_release import inventory
from test_preparation_runner import _acquisition, _reader, _run, _runner
from test_valuation_release_inputs import _client, _valuation_fixture
from test_working_capital_preparation import _recipe_plan


@pytest.mark.parametrize(
    "kind", ("working_capital", "conditional_capital", "conditional_reinvestment")
)
def test_different_plans_reuse_binding_bytes_without_reusing_dependency_identity(
    tmp_path, kind
):
    if kind == "working_capital":
        fixture = _valuation_fixture(tmp_path, sec_profile=True)
        plan = _recipe_plan(fixture)
    else:
        fixture = forward_fixture(tmp_path, sec_profile=True)
        plan = _plan(
            fixture,
            conditional_capital_recipe=capital_recipe(fixture.capital_policy),
            conditional_reinvestment_recipe=fixture.forward_policy.recipe,
        )
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    runner = _runner(fixture, acquisition=_acquisition(fixture))
    first = _reader(fixture, _run(runner, plan))
    assert first.status == "release_required"
    reference = getattr(first, kind + "_binding_ref")
    record = fixture.artifacts.get(reference.artifact_id)
    payloads = tuple(
        fixture.artifacts.root.glob(reference.content_hash + ".*.artifact")
    )
    assert len(payloads) == 1
    before = payloads[0].stat()

    other = type(plan).model_validate(
        plan.model_dump()
        | {"release_profile_id": plan.release_profile_id + "-alternate"}
    )
    publication = _run(runner, other)
    second = _reader(fixture, publication)
    assert second.status == "release_required"
    other_reference = getattr(second, kind + "_binding_ref")
    assert other_reference.artifact_id != reference.artifact_id
    assert other_reference.content_hash == reference.content_hash
    assert fixture.artifacts.read(
        other_reference.artifact_id
    ) == fixture.artifacts.read(reference.artifact_id)
    other_record = fixture.artifacts.get(other_reference.artifact_id)
    assert plan.digest in record.dependency_hashes
    assert other.digest in other_record.dependency_hashes
    assert other.digest not in record.dependency_hashes
    assert plan.digest not in other_record.dependency_hashes
    assert fixture.artifacts.get(reference.artifact_id) == record
    assert payloads[0].stat().st_mtime_ns == before.st_mtime_ns
    assert (
        tuple(fixture.artifacts.root.glob(reference.content_hash + ".*.artifact"))
        == payloads
    )
    saved = inventory(fixture.artifacts.root)
    repeat = _run(runner, other)
    assert not repeat.wrote and repeat.artifact == publication.artifact
    assert inventory(fixture.artifacts.root) == saved
