from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext

import pytest

from fundamental_service.contracts import DimensionV1, PeriodType, SourceRole, TraceV1
from fundamental_service.equity_dilution import (
    CommonShareQuoteV1,
    DilutionError,
    EquityAwardInventoryV1,
    PerformanceStockAwardV1,
    RestrictedStockAwardV1,
    StockOptionAwardV1,
    TreasuryStockPolicyV1,
    compute_treasury_stock_dilution,
)
from fundamental_service.serialization import canonical_bytes
from test_valuation_preparation import _fact

UTC = timezone.utc
VALUATION = datetime(2025, 1, 6, tzinfo=UTC)
INSTANT = datetime(2024, 6, 30, tzinfo=UTC).date()
AVAILABLE = datetime(2024, 7, 30, tzinfo=UTC)


def _observation(name, value, unit):
    fact = _fact(name, 2024, value, instant=True, available_at=AVAILABLE)
    return fact.model_copy(
        update={
            "issuer_id": "0000789019",
            "instant": INSTANT,
            "period_end": INSTANT,
            "as_of": datetime(2024, 6, 30, tzinfo=UTC),
            "source": fact.source.model_copy(
                update={"available_at": AVAILABLE, "filed_at": AVAILABLE}
            ),
            "unit": unit,
            "currency": None if unit == "xbrli:shares" else "USD",
            "context": fact.context.model_copy(
                update={
                    "instant": INSTANT,
                    "entity_scope": "0000789019",
                    "unit_qname": unit,
                }
            ),
        }
    )


def _inputs():
    restricted = RestrictedStockAwardV1(
        instrument_id="restricted",
        quantity=_observation("restricted-quantity", "240", "xbrli:shares"),
        unrecognized_compensation=_observation(
            "restricted-compensation", "1000", "iso4217:USD"
        ),
    )
    option = StockOptionAwardV1(
        instrument_id="option",
        quantity=_observation("option-quantity", "100", "xbrli:shares"),
        exercise_price=_observation(
            "option-exercise-price", "8", "iso4217:USD/xbrli:shares"
        ),
        unrecognized_compensation=_observation(
            "option-compensation", "50", "iso4217:USD"
        ),
    )
    trace = TraceV1(
        source_refs=(restricted.quantity.source.content_hash,),
        as_of=datetime(2024, 6, 30, tzinfo=UTC),
        available_at=AVAILABLE,
        captured_at=AVAILABLE,
        description="Synthetic completeness proposal; no actual mapping review.",
    )
    inventory = EquityAwardInventoryV1(
        issuer_id=restricted.quantity.issuer_id,
        security_id=restricted.quantity.security_id,
        currency="USD",
        period_end=INSTANT,
        complete_inventory=True,
        coverage_evidence=trace,
        instruments=(restricted, option),
    )
    quote = CommonShareQuoteV1(
        issuer_id=inventory.issuer_id,
        security_id=inventory.security_id,
        currency="USD",
        price=Decimal(10),
        source_id="synthetic-close",
        source_uri="https://example.invalid/quote",
        source_version="synthetic-v1",
        terms_reference="synthetic-test-only",
        content_hash="a" * 64,
        as_of=datetime(2025, 1, 3, 21, tzinfo=UTC),
        available_at=datetime(2025, 1, 3, 21, 15, tzinfo=UTC),
        captured_at=VALUATION,
    )
    policy = TreasuryStockPolicyV1(
        policy_version="synthetic-treasury-stock-v1", max_quote_age_seconds=3 * 86400
    )
    return inventory, quote, policy


def _compute(inventory, quote, policy):
    return compute_treasury_stock_dilution(
        inventory, quote, policy, valuation_timestamp=VALUATION
    )


def test_restricted_awards_and_options_use_treasury_stock_proceeds_and_retain_inputs():
    inventory, quote, policy = _inputs()
    result = _compute(inventory, quote, policy)
    rows = {row.instrument_id: row for row in result.instruments}
    assert rows["restricted"].incremental_shares == Decimal(140)
    assert rows["restricted"].exercise_proceeds == 0
    assert rows["option"].exercise_proceeds == Decimal(800)
    assert rows["option"].incremental_shares == Decimal(15)
    assert result.incremental_shares == Decimal(155)
    assert rows["option"].source_fact_ids == tuple(
        f.fact_id
        for f in (
            inventory.instruments[0].quantity,
            inventory.instruments[0].exercise_price,
            inventory.instruments[0].unrecognized_compensation,
        )
    )
    assert len(rows["option"].input_evidence_digests) == 3
    assert result.quote_content_hash == quote.content_hash
    assert not hasattr(result, "quality_status")


def test_excluded_anti_dilutive_awards_are_retained_per_class():
    inventory, quote, policy = _inputs()
    option = inventory.instruments[0]
    option = option.model_copy(
        update={
            "exercise_price": option.exercise_price.model_copy(
                update={"value": Decimal(12)}
            )
        }
    )
    inventory = inventory.model_copy(
        update={"instruments": (option, inventory.instruments[1])}
    )
    result = _compute(inventory, quote, policy)
    assert result.incremental_shares == Decimal(140)
    assert result.instruments[0].anti_dilutive
    assert result.instruments[0].incremental_shares == 0
    assert result.instruments[0].assumed_repurchased_shares == Decimal(125)


@pytest.mark.parametrize("dimensional", [False, True])
def test_reviewed_inventory_keeps_parser_scope_without_rewriting_originals(dimensional):
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    dimensions = (
        (DimensionV1(name="us-gaap:AwardTypeAxis", member="synthetic:RSU"),)
        if dimensional
        else ()
    )
    scope = "segmented" if dimensional else "unspecified"
    facts = tuple(
        fact.model_copy(
            update={
                "security_scope": scope,
                "context": fact.context.model_copy(
                    update={
                        "dimensions": dimensions,
                        "consolidation_scope": "segmented"
                        if dimensional
                        else "consolidated",
                    }
                ),
            }
        )
        for fact in (award.quantity, award.unrecognized_compensation)
    )
    inventory = inventory.model_copy(
        update={
            "instruments": (
                award.model_copy(
                    update={"quantity": facts[0], "unrecognized_compensation": facts[1]}
                ),
            )
        }
    )
    result = _compute(inventory, quote, policy)
    assert result.incremental_shares == Decimal(140)
    assert inventory.instruments[0].quantity.security_scope == scope
    assert result.instruments[0].input_evidence_digests


@pytest.mark.parametrize("scope", ["OTHER", "unknown", "segmented", None])
def test_inventory_cannot_bind_unknown_other_or_inconsistent_parser_scope(scope):
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    award = award.model_copy(
        update={"quantity": award.quantity.model_copy(update={"security_scope": scope})}
    )
    inventory = inventory.model_copy(update={"instruments": (award,)})
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == "DILUTION_FACT_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "axis", ["us-gaap:StatementClassOfStockAxis", "us-gaap:StatementGeographicalAxis"]
)
def test_parser_segment_scope_does_not_authorize_other_share_or_entity_dimensions(axis):
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    quantity = award.quantity.model_copy(
        update={
            "security_scope": "segmented",
            "context": award.quantity.context.model_copy(
                update={
                    "dimensions": (DimensionV1(name=axis, member="synthetic:Other"),),
                    "consolidation_scope": "segmented",
                }
            ),
        }
    )
    inventory = inventory.model_copy(
        update={"instruments": (award.model_copy(update={"quantity": quantity}),)}
    )
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == "DILUTION_FACT_SCOPE_MISMATCH"


def test_order_digest_repeat_and_hostile_decimal_context_are_deterministic():
    inventory, quote, policy = _inputs()
    first = _compute(inventory, quote, policy)
    data = inventory.model_dump()
    data["instruments"] = tuple(reversed(inventory.instruments))
    reordered = EquityAwardInventoryV1.model_validate(data)
    assert reordered == inventory
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        repeated = _compute(reordered, quote, policy)
    assert canonical_bytes(repeated) == canonical_bytes(first)
    assert repeated.digest == first.digest


@pytest.mark.parametrize(
    "change,code",
    [
        ({"currency": "EUR"}, "DILUTION_QUOTE_SCOPE_MISMATCH"),
        ({"issuer_id": "0000000002"}, "DILUTION_QUOTE_SCOPE_MISMATCH"),
        ({"security_id": "OTHER"}, "DILUTION_QUOTE_SCOPE_MISMATCH"),
        (
            {
                "available_at": VALUATION + timedelta(seconds=1),
                "captured_at": VALUATION + timedelta(seconds=1),
            },
            "DILUTION_FUTURE_EVIDENCE",
        ),
        ({"as_of": VALUATION - timedelta(days=4)}, "DILUTION_QUOTE_STALE"),
    ],
)
def test_quotes_reject_foreign_future_or_stale_evidence(change, code):
    inventory, quote, policy = _inputs()
    data = quote.model_dump()
    data.update(change)
    quote = CommonShareQuoteV1.model_validate(data)
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == code


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity"])
def test_quote_requires_positive_finite_price(price):
    _, quote, _ = _inputs()
    data = quote.model_dump()
    data["price"] = Decimal(price)
    with pytest.raises(ValueError):
        CommonShareQuoteV1.model_validate(data)


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"instant": datetime(2023, 6, 30, tzinfo=UTC).date()},
            "DILUTION_FACT_SCOPE_MISMATCH",
        ),
        ({"issuer_id": "0000000002"}, "DILUTION_FACT_SCOPE_MISMATCH"),
        ({"security_id": "OTHER"}, "DILUTION_FACT_SCOPE_MISMATCH"),
        ({"unit": "xbrli:shares"}, "DILUTION_UNIT_MISMATCH"),
        ({"currency": "EUR"}, "DILUTION_UNIT_MISMATCH"),
        (
            {"available_at": VALUATION + timedelta(seconds=1)},
            "DILUTION_FUTURE_EVIDENCE",
        ),
        ({"value": Decimal("NaN")}, "DILUTION_FACT_INVALID"),
        ({"value": Decimal(-1)}, "DILUTION_FACT_INVALID"),
    ],
)
def test_award_inputs_reject_mixed_scope_unit_period_future_or_invalid_amount(
    change, code
):
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    award = award.model_copy(
        update={
            "unrecognized_compensation": award.unrecognized_compensation.model_copy(
                update=change
            )
        }
    )
    inventory = inventory.model_copy(
        update={"instruments": (inventory.instruments[0], award)}
    )
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == code


def test_inventory_cannot_reuse_an_original_observation_under_another_identity():
    inventory, _, _ = _inputs()
    award = inventory.instruments[1]
    duplicate = award.model_copy(update={"instrument_id": "duplicate"})
    with pytest.raises(ValueError, match="observation twice"):
        EquityAwardInventoryV1.model_validate(
            {
                **inventory.model_dump(),
                "instruments": (*inventory.instruments, duplicate),
            }
        )


def test_unresolved_performance_conditions_abstain_with_retained_source_inputs():
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    conditional = PerformanceStockAwardV1(
        instrument_id="conditional",
        quantity=award.quantity,
        unrecognized_compensation=award.unrecognized_compensation,
        conditions_satisfied=False,
        condition_evidence=inventory.coverage_evidence,
    )
    inventory = inventory.model_copy(update={"instruments": (conditional,)})
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == "DILUTION_PERFORMANCE_UNRESOLVED"
    assert inventory.instruments[0].condition_evidence.source_refs


def test_duration_eps_cannot_supply_point_in_time_awards():
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    duration = award.quantity.model_copy(
        update={
            "instant": None,
            "period_start": datetime(2024, 1, 1, tzinfo=UTC).date(),
            "context": award.quantity.context.model_copy(
                update={
                    "instant": None,
                    "period_type": PeriodType.DURATION,
                    "start_date": datetime(2024, 1, 1, tzinfo=UTC).date(),
                    "end_date": INSTANT,
                }
            ),
        }
    )
    inventory = inventory.model_copy(
        update={"instruments": (award.model_copy(update={"quantity": duration}),)}
    )
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == "DILUTION_FACT_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "change",
    [
        {"is_amendment": True},
        {"accession_number": "different-original"},
        {"source_role": SourceRole.MARKET},
        {"accession_number": None},
    ],
)
def test_awards_require_the_same_original_filing(change):
    inventory, quote, policy = _inputs()
    award = inventory.instruments[1]
    if "source_role" in change:
        quantity = award.quantity.model_copy(
            update={"source": award.quantity.source.model_copy(update=change)}
        )
    else:
        quantity = award.quantity.model_copy(update=change)
    inventory = inventory.model_copy(
        update={"instruments": (award.model_copy(update={"quantity": quantity}),)}
    )
    with pytest.raises(DilutionError) as error:
        _compute(inventory, quote, policy)
    assert error.value.code == "DILUTION_FACT_SCOPE_MISMATCH"


@pytest.mark.parametrize("dimensional", [False, True])
def test_duplicate_context_aliases_and_total_component_overlap_are_rejected(
    dimensional,
):
    inventory, _, _ = _inputs()
    original = inventory.instruments[1]
    changes = {"context_id": "context-alias"}
    if dimensional:
        changes.update(
            dimensions=(
                DimensionV1(
                    name="us-gaap:AwardTypeAxis", member="us-gaap:RestrictedStockMember"
                ),
            ),
            consolidation_scope="segmented",
        )
    quantity = original.quantity.model_copy(
        update={
            "fact_id": "quantity-alias",
            "context": original.quantity.context.model_copy(update=changes),
        }
    )
    compensation = original.unrecognized_compensation.model_copy(
        update={
            "fact_id": "compensation-alias",
            "concept": "us-gaap:DifferentCompensation",
            "context": original.unrecognized_compensation.context.model_copy(
                update={"concept_qname": "us-gaap:DifferentCompensation"}
            ),
        }
    )
    duplicate = original.model_copy(
        update={
            "instrument_id": "alias",
            "quantity": quantity,
            "unrecognized_compensation": compensation,
        }
    )
    with pytest.raises(
        ValueError,
        match="totals with class components" if dimensional else "observation twice",
    ):
        EquityAwardInventoryV1.model_validate(
            {
                **inventory.model_dump(),
                "instruments": (*inventory.instruments, duplicate),
            }
        )
