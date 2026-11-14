"""Conditional pool bounds contain the official per-strike dilution arithmetic."""

from datetime import date
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from itertools import product

import pytest
from pydantic import ValidationError

from fundamental_service.equity_dilution import (
    EquityAwardInventoryV1,
    compute_treasury_stock_dilution,
)
from fundamental_service.option_pool_research import (
    AVERAGE_STRIKE_CONCEPT,
    QUANTITY_CONCEPT,
    OptionPoolResearchRequestV1,
    OptionPoolScenarioV1,
    research_option_pool_bounds,
)
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_original_issuer import DECISION, original
from test_equity_dilution import VALUATION, _inputs, _observation


def _request(*, count="2", average="10", compensation="0", error="0", changes=None):
    report, source = original()
    base = next(fact for fact in report.facts if fact.is_numeric)
    quantity = base.model_copy(
        update={
            "concept": QUANTITY_CONCEPT,
            "value": count,
            "unit": "xbrli:shares",
            "context_id": "options",
            "period_start": None,
            "period_end": None,
            "instant": date(2025, 12, 31),
            "decimals": "INF",
            "security_scope": "unspecified",
        }
    )
    price = quantity.model_copy(
        update={
            "concept": AVERAGE_STRIKE_CONCEPT,
            "value": average,
            "unit": "iso4217:USD/xbrli:shares",
        }
    )
    if changes:
        quantity = quantity.model_copy(update=changes)
    source_report = report.model_copy(
        update={"facts": (*report.facts, quantity, price)}
    )
    evidence = evaluate_original_issuer(
        source_report, source=source, decision_at=DECISION
    )
    return OptionPoolResearchRequestV1(
        original=evidence,
        period_end=date(2025, 12, 31),
        quantity_fact_digest=sha256_digest(quantity),
        average_strike_fact_digest=sha256_digest(price),
        instrument_assumption="one_share_nonnegative_strike_treasury_stock",
        instrument_assumption_rationale="Synthetic conventional options, each for one underlying share.",
        assumed_average_strike_error=Decimal(error),
        strike_error_rationale="Synthetic exact average assumption for a mathematical boundary test.",
        scenarios=(
            OptionPoolScenarioV1(
                scenario_id="hypothetical-10",
                hypothetical_price=Decimal(10),
                assumed_compensation_upper_bound=(
                    Decimal(compensation) if compensation is not None else None
                ),
                compensation_assumption_rationale=(
                    "Synthetic compensation cap; no issuer mapping or source approval."
                    if compensation is not None
                    else None
                ),
            ),
        ),
    )


def test_same_average_does_not_identify_dilution_and_unknown_cost_stays_unknown():
    request = _request()
    result = research_option_pool_bounds(request)
    assert result.status == "provisional_conditional_bounds"
    assert result.bounds[0].incremental_shares_lower == 0
    assert result.bounds[0].incremental_shares_upper == 2
    assert result.complete_inventory is False
    assert result.supported_history_threshold is None
    assert "issuer_valuation" in result.unestablished_claims
    unknown = research_option_pool_bounds(_request(average="1", compensation=None))
    assert unknown.bounds[0].incremental_shares_lower == 0
    assert unknown.bounds[0].scenario.assumed_compensation_upper_bound is None
    assert result.source_content_hash == request.original.source.content_hash
    assert result.parser_input_hash == request.original.source.parser_input_hash
    assert tuple(sha256_digest(f) for f in result.observations) == (
        request.quantity_fact_digest,
        request.average_strike_fact_digest,
    )
    with pytest.raises(ValidationError):
        EquityAwardInventoryV1.model_validate(result.model_dump())


def test_outward_bounds_contain_enumerated_official_per_strike_results():
    inventory, quote, policy = _inputs()
    option = inventory.instruments[0]
    for strikes in product((0, 5, 15), repeat=3):
        for costs in product((0, 2), repeat=3):
            request = _request(
                count="3",
                average=str(Decimal(sum(strikes)) / 3),
                compensation=str(sum(costs)),
                error="1e-25",
            )
            # The reporting-error allowance covers the host's repeating average.
            for price in (3, 10, 30):
                scenario = request.scenarios[0].model_copy(
                    update={"hypothetical_price": Decimal(price)}
                )
                bound = research_option_pool_bounds(
                    request.model_copy(update={"scenarios": (scenario,)})
                ).bounds[0]
                instruments = tuple(
                    option.model_copy(
                        update={
                            "instrument_id": str(i),
                            "quantity": _observation(f"q-{i}", "1", "xbrli:shares"),
                            "exercise_price": _observation(
                                f"k-{i}", str(strike), "iso4217:USD/xbrli:shares"
                            ),
                            "unrecognized_compensation": _observation(
                                f"c-{i}", str(cost), "iso4217:USD"
                            ),
                        }
                    )
                    for i, (strike, cost) in enumerate(zip(strikes, costs, strict=True))
                )
                actual = compute_treasury_stock_dilution(
                    inventory.model_copy(update={"instruments": instruments}),
                    quote.model_copy(update={"price": Decimal(price)}),
                    policy,
                    valuation_timestamp=VALUATION,
                )
                assert bound.incremental_shares_lower <= actual.incremental_shares
                assert actual.incremental_shares <= bound.incremental_shares_upper


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"unit": "iso4217:USD"}, "OPTION_POOL_OBSERVATION_SCOPE_INVALID"),
        ({"entity_identifier": "2"}, "OPTION_POOL_OBSERVATION_SCOPE_INVALID"),
        (
            {"dimensions": (("us-gaap:AwardTypeAxis", "custom:Pool"),)},
            "OPTION_POOL_OBSERVATION_SCOPE_INVALID",
        ),
        ({"value": "2.5"}, "OPTION_POOL_WHOLE_COUNT_UNESTABLISHED"),
        ({"decimals": "-3"}, "OPTION_POOL_WHOLE_COUNT_UNESTABLISHED"),
        ({"value": "-2"}, "OPTION_POOL_OBSERVATION_INVALID"),
        ({"value": "NaN"}, "OPTION_POOL_OBSERVATION_INVALID"),
    ),
)
def test_wrong_observation_is_retained_as_deterministic_refusal(changes, code):
    request = _request(changes=changes)
    result = research_option_pool_bounds(request)
    assert result.status == "abstained" and not result.bounds
    assert result.issue_codes == (code,)
    assert result.input_digest == sha256_digest(request)
    assert canonical_bytes(result) == canonical_bytes(
        research_option_pool_bounds(request)
    )


def test_missing_fact_conflicting_duplicate_future_original_and_wrong_period_refuse():
    request = _request()
    missing = request.model_copy(update={"quantity_fact_digest": "0" * 64})
    assert research_option_pool_bounds(missing).issue_codes == (
        "OPTION_POOL_OBSERVATION_MISSING",
    )
    original = request.original
    selected = next(f for f in original.report.facts if f.concept == QUANTITY_CONCEPT)
    conflict = selected.model_copy(update={"value": "3", "context_id": "conflict"})
    report = original.report.model_copy(
        update={"facts": (*original.report.facts, conflict)}
    )
    updated = evaluate_original_issuer(
        report, source=original.source, decision_at=original.decision_at
    )
    assert research_option_pool_bounds(
        request.model_copy(update={"original": updated})
    ).issue_codes == ("OPTION_POOL_OBSERVATION_CONFLICT",)
    future = evaluate_original_issuer(
        original.report,
        source=original.source,
        decision_at=original.source.available_at.replace(year=2025),
    )
    for changed in (
        request.model_copy(update={"original": future}),
        request.model_copy(update={"period_end": date(2026, 12, 31)}),
    ):
        assert research_option_pool_bounds(changed).issue_codes == (
            "OPTION_POOL_ORIGINAL_UNAVAILABLE",
        )


def test_scenario_order_and_ambient_decimal_state_do_not_change_outputs():
    request = _request(count="7", average="1", compensation="0")
    first = request.scenarios[0]
    second = first.model_copy(
        update={"scenario_id": "other", "hypothetical_price": Decimal(3)}
    )
    request = OptionPoolResearchRequestV1.model_validate(
        {**request.model_dump(), "scenarios": (second, first)}
    )
    expected = research_option_pool_bounds(request)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert canonical_bytes(research_option_pool_bounds(request)) == canonical_bytes(
            expected
        )
    assert expected.output_digest == sha256_digest(expected)
    assert [b.scenario.scenario_id for b in expected.bounds] == [
        "hypothetical-10",
        "other",
    ]
    with pytest.raises(ValidationError, match="unique"):
        OptionPoolResearchRequestV1.model_validate(
            {**request.model_dump(), "scenarios": (first, first)}
        )


def test_declared_rounding_precision_requires_an_adequate_error_allowance():
    request = _request()
    original = request.original
    price = next(
        f for f in original.report.facts if f.concept == AVERAGE_STRIKE_CONCEPT
    )
    rounded = price.model_copy(update={"decimals": "2"})
    report = original.report.model_copy(
        update={
            "facts": tuple(rounded if f == price else f for f in original.report.facts)
        }
    )
    updated = evaluate_original_issuer(
        report, source=original.source, decision_at=DECISION
    )
    request = request.model_copy(
        update={
            "original": updated,
            "average_strike_fact_digest": sha256_digest(rounded),
        }
    )
    assert research_option_pool_bounds(request).issue_codes == (
        "OPTION_POOL_STRIKE_ERROR_TOO_SMALL",
    )
    adequate = request.model_copy(
        update={"assumed_average_strike_error": Decimal("0.005")}
    )
    assert (
        research_option_pool_bounds(adequate).status == "provisional_conditional_bounds"
    )


@pytest.mark.parametrize("price", ("0", "-1", "NaN", "Infinity"))
def test_invalid_hypothetical_prices_are_rejected_at_the_boundary(price):
    with pytest.raises(ValidationError):
        OptionPoolScenarioV1(scenario_id="invalid", hypothetical_price=Decimal(price))


def test_a_compensation_assumption_cannot_be_implicit():
    with pytest.raises(ValidationError, match="rationale"):
        OptionPoolScenarioV1(
            scenario_id="invalid",
            hypothetical_price=Decimal(10),
            assumed_compensation_upper_bound=Decimal(0),
        )


def test_lower_bound_rounds_outward_and_zero_count_remains_zero():
    request = _request(count="7", average="1", compensation="0")
    scenario = request.scenarios[0].model_copy(
        update={"hypothetical_price": Decimal(3)}
    )
    result = research_option_pool_bounds(
        request.model_copy(update={"scenarios": (scenario,)})
    )
    with localcontext() as context:
        context.prec = 100
        actual = Decimal(7) - Decimal(7) / 3
        lower = result.bounds[0].incremental_shares_lower
        assert lower <= actual and actual - lower < Decimal("1e-48")
    zero = research_option_pool_bounds(_request(count="0", compensation=None))
    assert zero.bounds[0].incremental_shares_lower == 0
    assert zero.bounds[0].incremental_shares_upper == 0
