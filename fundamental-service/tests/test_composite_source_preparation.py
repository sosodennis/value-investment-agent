"""Explicit source-plan input policy is preserved through release and calculation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import (
    CallerApprovalEnvelopeV1,
    SecMappingReferenceV1,
)
from fundamental_service.automatic_source_mapping import AutomaticSecIngestionRequestV1
from fundamental_service.facts import FilesystemCanonicalFactRepository
from fundamental_service.preparation_runner import (
    AutomaticSourcePreparationPlanV1,
    SourcePreparationPlanV2,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.working_capital import canonical_working_capital_inputs
from test_postgres_metadata import _sec_ingestion_request
from test_automatic_source_mapping import source_case
from test_preparation_runner import (
    REVISION,
    VALUATION_TIME,
    _reader,
    _reviewed_candidate,
    _run,
    _runner,
    _fixture,
)
from test_valuation_release_inputs import (
    _client,
    _manifest_with,
    _valuation_fixture,
)
from test_issuer_operating_release import inventory


def _plan(fixture):
    snapshot = fixture.snapshot
    base = _sec_ingestion_request()
    request = type(base)(
        **(
            base.model_dump()
            | {
                field: getattr(snapshot, field)
                for field in (
                    "identity",
                    "valuation_timestamp",
                    "fiscal_period_selector",
                    "parser_version",
                    "policy_version",
                    "taxonomy_manifest_id",
                    "validation_profile_id",
                )
            }
            | {
                "cik": snapshot.identity.issuer_id,
                "ticker": snapshot.identity.security_id,
                "identity_basis": "original-filing-dei-v1",
                "required_fields": tuple(
                    sorted(
                        mapping.normalized_field
                        for mapping in fixture.mappings.values()
                    )
                ),
                "filing": base.filing.model_copy(
                    update={
                        "accession_number": snapshot.source_records[0].accession_number,
                        "forms": ("10-K",),
                    }
                ),
                "mappings": tuple(
                    SecMappingReferenceV1(
                        decision_id=mapping.decision_id,
                        mapping_version=mapping.mapping_version,
                        normalized_field=mapping.normalized_field,
                    )
                    for mapping in fixture.mappings.values()
                ),
            }
        )
    )
    return SourcePreparationPlanV2(
        source_revision=REVISION,
        release_profile_id=fixture.manifest.profile_id,
        model_id="fcff_dcf",
        ingestions=(request,),
        valuation_working_capital_policy=fixture.manifest.valuation_working_capital_policy,
    )


def test_explicit_composite_plan_uses_formal_flow_and_reuses_calculation(tmp_path):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture)
    candidate, canary = _reviewed_candidate(fixture)
    fixture.state.active = None
    fixture.application = _client(fixture).app.state.application
    runner = _runner(fixture, canary=canary)
    prepared_receipt = _run(runner, plan, candidate=candidate)
    prepared = _reader(fixture, prepared_receipt)
    assert prepared.status == "approval_required"
    assert prepared.preparation.input is not None
    assert (
        prepared.preparation.historical_metrics.working_capital_inputs == fixture.inputs
    )
    assert "WORKING_CAPITAL_INPUT_ESTIMATED" in prepared.preparation.issue_codes
    assert plan.requirements_profile.supported_history_threshold is None
    assert (
        "cash_and_short_term_investments"
        in plan.requirements_profile.supporting_fact_fields
    )
    assert "current_assets" in plan.resolution_request().required_fields
    approval = CallerApprovalEnvelopeV1(
        input_digest=prepared.preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    calculated = _run(runner, plan, approval=approval)
    evidence = _reader(fixture, calculated)
    assert evidence.status == "calculated"
    assert evidence.calculation.base.per_share_value > 0
    assert evidence.calculation.base.quality_status.value == "provisional"
    before = inventory(fixture.artifacts.root)
    repeated = _run(_runner(fixture), plan, approval=approval, correlation="second")
    assert repeated.artifact == calculated.artifact and repeated.wrote is False
    assert inventory(fixture.artifacts.root) == before


def test_source_plan_rejects_a_different_release_input_policy_before_writes(tmp_path):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture)
    fixture.manifest = _manifest_with(
        fixture.manifest, valuation_working_capital_policy=None
    )
    candidate, canary = _reviewed_candidate(fixture)
    fixture.application = _client(fixture).app.state.application
    before = inventory(fixture.artifacts.root)
    with pytest.raises(ValueError, match="candidate does not match"):
        _run(_runner(fixture, canary=canary), plan, candidate=candidate)
    assert inventory(fixture.artifacts.root) == before


@pytest.mark.parametrize("pin", ["issuer_id", "accession_number", "mapping_version"])
def test_source_plan_input_policy_cannot_escape_issuer_filing_or_mapping(tmp_path, pin):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture)
    policy = plan.valuation_working_capital_policy
    payload = policy.model_dump()
    payload["inputs"] = canonical_working_capital_inputs(
        tuple(item.model_copy(update={pin: "different"}) for item in policy.inputs)
    )
    if pin == "mapping_version":
        payload[pin] = "different"
    policy = type(policy)(**payload)
    with pytest.raises(ValidationError):
        type(plan)(**(plan.model_dump() | {"valuation_working_capital_policy": policy}))


def test_ordinary_source_plan_keeps_its_bytes_and_identity(tmp_path):
    plan = _fixture(tmp_path).plan
    payload = plan.model_dump()
    assert "valuation_working_capital_policy" not in payload
    assert sha256_digest(payload) == plan.digest
    assert canonical_bytes(
        type(plan).model_validate_json(canonical_bytes(payload))
    ) == canonical_bytes(plan)


@pytest.mark.parametrize(
    "change", ["complete", "missing", "foreign_mapping", "future", "unknown"]
)
def test_composed_history_requires_every_declared_exclusion(tmp_path, change):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture)
    fact_id = "cash_and_short_term_investments-2021"
    if change == "unknown":
        policy = plan.valuation_working_capital_policy
        inputs = tuple(
            type(item)(
                **(
                    item.model_dump()
                    | {
                        "exclusions": tuple(
                            type(exclusion)(
                                **(
                                    exclusion.model_dump()
                                    | {"state": "unknown", "fact_id": None}
                                )
                            )
                            if exclusion.fact_id == fact_id
                            else exclusion
                            for exclusion in item.exclusions
                        )
                    }
                )
            )
            for item in policy.inputs
        )
        plan = type(plan)(
            **(
                plan.model_dump()
                | {
                    "valuation_working_capital_policy": type(policy)(
                        **(policy.model_dump() | {"inputs": inputs})
                    )
                }
            )
        )
    elif change != "complete":
        repository = FilesystemCanonicalFactRepository(tmp_path / "changed-facts")
        for fact in fixture.facts.list():
            if fact.fact_id == fact_id:
                if change == "missing":
                    continue
                fact = type(fact)(
                    **(
                        fact.model_dump()
                        | (
                            {"mapping_decision_id": "foreign-mapping"}
                            if change == "foreign_mapping"
                            else {
                                "available_at": datetime(2027, 1, 1, tzinfo=UTC),
                                "captured_at": datetime(2027, 1, 1, tzinfo=UTC),
                            }
                        )
                    )
                )
            repository.publish(fact)
        fixture.facts = repository
    fixture.application = _client(fixture).app.state.application
    runner = _runner(fixture)
    issues, missing = runner._assess_history_requirements(plan, fixture.snapshot)
    if change == "complete":
        assert (issues, missing) == ((), ())
        return
    assert issues == ("SOURCE_PREPARATION_WORKING_CAPITAL_INVALID",)
    assert (
        "WORKING_CAPITAL_EXCLUSION_UNKNOWN:cash_and_investments_combined"
        if change == "unknown"
        else f"WORKING_CAPITAL_FACT_MISSING:{fact_id}"
    ) in missing
    before = inventory(fixture.artifacts.root)
    assert runner._assess_history_requirements(plan, fixture.snapshot) == (
        issues,
        missing,
    )
    assert inventory(fixture.artifacts.root) == before


@pytest.mark.parametrize("change", ["complete", "ordinary_profile", "mapping"])
def test_automatic_plan_pins_the_source_profile_and_policy(tmp_path, change):
    fixture = _valuation_fixture(tmp_path / "valuation", sec_profile=True)
    plan = _plan(fixture)
    automatic, *_ = source_case(tmp_path / "automatic")
    payload = automatic.model_dump() | plan.ingestions[0].model_dump(
        exclude={"mappings"}
    )
    payload.update(
        source_revision=plan.source_revision,
        requirements_digest=plan.requirements_profile.digest,
        required_fields=plan.requirements_profile.required_fact_fields,
        mapping_version=plan.valuation_working_capital_policy.mapping_version,
    )
    if change == "mapping":
        payload["mapping_version"] = "different-mapping"
    elif change == "ordinary_profile":
        payload["requirements_digest"] = automatic.requirements_digest
        payload["required_fields"] = automatic.required_fields
    request = AutomaticSecIngestionRequestV1(**payload)
    plan_payload = plan.model_dump(exclude={"protocol"}) | {"ingestions": (request,)}
    if change == "complete":
        result = AutomaticSourcePreparationPlanV1(**plan_payload)
        assert result.requirements_profile == plan.requirements_profile
    else:
        with pytest.raises(ValidationError):
            AutomaticSourcePreparationPlanV1(**plan_payload)


def test_composed_history_requires_a_composite_policy_input_for_each_annual_period(
    tmp_path,
):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture)
    policy = plan.valuation_working_capital_policy
    plan = type(plan)(
        **(
            plan.model_dump()
            | {
                "valuation_working_capital_policy": type(policy)(
                    **(
                        policy.model_dump()
                        | {
                            "inputs": tuple(
                                item
                                for item in policy.inputs
                                if item.period_end.year != 2024
                            )
                        }
                    )
                )
            }
        )
    )
    fixture.application = _client(fixture).app.state.application
    assert _runner(fixture)._assess_history_requirements(plan, fixture.snapshot) == (
        ("HISTORY_MINIMUM_PERIODS_UNAVAILABLE",),
        ("2024:working_capital_policy_input",),
    )
