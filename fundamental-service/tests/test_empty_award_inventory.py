"""Explicit reviewed absence is distinct from missing award evidence."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import CallerApprovalEnvelopeV1, QualityStatus
from fundamental_service.equity_award_evidence import verify_dilution_fact_bindings
from fundamental_service.equity_dilution import (
    DilutionError,
    EquityAwardInventoryV1,
    compute_treasury_stock_dilution,
)
from fundamental_service.serialization import canonical_bytes
from test_equity_dilution import VALUATION, _inputs
from test_preparation_runner import (
    VALUATION_TIME,
    _fixture,
    _reader,
    _reviewed_candidate,
    _run,
    _runner,
)


def test_explicit_complete_empty_inventory_round_trips_and_repeats():
    inventory, quote, policy = _inputs()
    empty = EquityAwardInventoryV1.model_validate(
        {**inventory.model_dump(), "instruments": ()}
    )
    restored = EquityAwardInventoryV1.model_validate_json(canonical_bytes(empty))
    first = compute_treasury_stock_dilution(
        empty, quote, policy, valuation_timestamp=VALUATION
    )
    repeated = compute_treasury_stock_dilution(
        restored, quote, policy, valuation_timestamp=VALUATION
    )
    assert first.incremental_shares == Decimal(0)
    assert first.instruments == ()
    assert canonical_bytes(first) == canonical_bytes(repeated)
    assert first.input_digest == repeated.input_digest
    assert first.quote_content_hash == quote.content_hash


@pytest.mark.parametrize("case", ["missing", "null", "incomplete"])
def test_empty_inventory_still_requires_explicit_complete_inventory(case):
    inventory, _, _ = _inputs()
    payload = {**inventory.model_dump(), "instruments": ()}
    if case == "missing":
        del payload["instruments"]
    elif case == "null":
        payload["instruments"] = None
    else:
        payload["complete_inventory"] = False
    with pytest.raises(ValidationError):
        EquityAwardInventoryV1.model_validate(payload)


@pytest.mark.parametrize("field", ["source_refs", "as_of", "available_at"])
def test_empty_inventory_still_requires_exact_dated_source_coverage(field):
    inventory, quote, policy = _inputs()
    trace = inventory.coverage_evidence.model_copy(
        update={field: () if field == "source_refs" else None}
    )
    empty = EquityAwardInventoryV1.model_validate(
        {**inventory.model_dump(), "instruments": (), "coverage_evidence": trace}
    )
    with pytest.raises(DilutionError) as error:
        compute_treasury_stock_dilution(
            empty, quote, policy, valuation_timestamp=VALUATION
        )
    assert error.value.code == "DILUTION_COVERAGE_UNAVAILABLE"


def test_empty_inventory_cannot_hide_released_award_observations(tmp_path):
    fixture = _fixture(tmp_path)
    empty = EquityAwardInventoryV1.model_validate(
        {**fixture.dilution.inventory.model_dump(), "instruments": ()}
    )
    with pytest.raises(DilutionError) as error:
        verify_dilution_fact_bindings(
            fixture.dilution.model_copy(update={"inventory": empty}),
            snapshot=fixture.snapshot,
            released_facts=fixture.facts.list(),
        )
    assert error.value.code == "DILUTION_INVENTORY_INCOMPLETE"


def test_empty_inventory_cannot_cite_an_unknown_original(tmp_path):
    fixture = _fixture(tmp_path, empty_awards=True)
    inventory = fixture.dilution.inventory.model_copy(
        update={
            "coverage_evidence": fixture.dilution.inventory.coverage_evidence.model_copy(
                update={"source_refs": ("f" * 64,)}
            )
        }
    )
    with pytest.raises(DilutionError) as error:
        verify_dilution_fact_bindings(
            fixture.dilution.model_copy(update={"inventory": inventory}),
            snapshot=fixture.snapshot,
            released_facts=fixture.facts.list(),
        )
    assert error.value.code == "DILUTION_REVIEW_SOURCE_MISMATCH"


def test_signed_empty_inventory_prepares_calculates_and_reuses_without_zero_facts(
    tmp_path,
):
    fixture = _fixture(tmp_path, released=False, empty_awards=True)
    candidate, canary = _reviewed_candidate(fixture)
    canary.validate(candidate.manifest, candidate.verification)
    runner = _runner(fixture, canary=canary)
    prepared = _reader(
        fixture, _run(runner, fixture.plan, candidate=candidate)
    ).preparation
    assert prepared.status == "prepared"
    assert prepared.equity_dilution.incremental_shares == 0
    assert prepared.equity_dilution.instruments == ()
    assert prepared.input.assumptions.capital_bridge.diluted_shares == Decimal(110)
    assert not any(
        fact.normalized_field.startswith("equity_award_")
        for fact in fixture.facts.list()
    )
    approval = CallerApprovalEnvelopeV1(
        input_digest=prepared.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    first = _run(runner, fixture.plan, approval=approval)
    repeated = _run(runner, fixture.plan, approval=approval, correlation="repeat")
    result = _reader(fixture, first)
    assert result.status == "calculated"
    assert result.calculation.base.per_share_value > 0
    assert result.calculation.base.quality_status is QualityStatus.PROVISIONAL
    assert first.artifact == repeated.artifact
    assert repeated.wrote is False
