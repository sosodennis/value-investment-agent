"""Operating accuracy has explicit evidence scope and shares full-model math."""

import json
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.calculator import calculate
from fundamental_service.contracts import (
    CanonicalFactV1,
    DimensionV1,
    IdentityV1,
    QualityStatus,
    SourceRole,
    SourceSnapshotV1,
    UncertaintyV1,
)
from fundamental_service.operating_forecast import (
    OperatingForecastV1,
    prepare_operating_forecast,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import (
    operating_forecast_requirements_profile,
    valuation_requirements_profile,
)
from test_postgres_metadata import _snapshot
from test_valuation_preparation import (
    RELEASE_DIGEST,
    VALUATION_TIME,
    _fact,
    _facts,
    _market_policy,
    _prepare,
)


def snapshot() -> SourceSnapshotV1:
    return _snapshot(
        "operating-forecast",
        identity=IdentityV1(
            issuer_id="CIK1",
            issuer_name="Example Co",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="COMMON",
            share_class="common",
            currency="USD",
        ),
        valuation_timestamp=VALUATION_TIME,
    )


def operating_facts() -> tuple[CanonicalFactV1, ...]:
    roles = operating_forecast_requirements_profile("fcff_dcf").required_fact_fields
    return tuple(fact for fact in _facts() if fact.normalized_field in roles)


def prepare(
    facts: tuple[CanonicalFactV1, ...],
    *,
    model_id="fcff_dcf",
    **changes,
) -> OperatingForecastV1:
    return prepare_operating_forecast(
        facts,
        **{
            "snapshot": snapshot(),
            "model_id": model_id,
            "model_version": f"{model_id}-v1",
            "policy_id": "fcff_dcf-us-gaap-public-v1",
            "policy_version": "fcff_dcf-v1-quality-v1",
            "mapping_version": "sec-canonical-mapping-v1",
            "data_release_manifest_digest": RELEASE_DIGEST,
            **changes,
        },
    )


@pytest.mark.parametrize("model", ("fcff_dcf", "transition_fcff_dcf"))
def test_operating_targets_equal_full_valuation_without_dummy_capital_or_market(model):
    filing = _fact("filed_operating_evidence", 2025, "1").model_copy(
        update={"value": "filed evidence"}
    )
    extra = (filing,) if model == "transition_fcff_dcf" else ()
    operating = prepare((*operating_facts(), *extra), model_id=model)
    full = _prepare((*_facts(), *extra), market_policy=_market_policy(), model_id=model)
    assert full.input is not None
    request = full.input.model_copy(
        update={"uncertainty": UncertaintyV1(mode="none")}
    ).with_digest()
    calculated = calculate(request, allow_provisional=True)
    expected = {
        node.node_id: node.value
        for node in calculated.nodes
        if node.node_id.startswith(("revenue_", "fcff_"))
    }
    assert {node.node_id: node.value for node in operating.nodes[1:]} == expected
    assert operating.forecast == full.input.assumptions.forecast
    assert operating.tax_rate == full.input.assumptions.wacc.tax_rate
    assert operating.status == "prepared"
    assert operating.quality_status is QualityStatus.PROVISIONAL
    assert operating.supported_history_threshold is None
    assert "HISTORY_THRESHOLD_UNVALIDATED" in operating.issue_codes
    assert not {"per_share_value", "wacc", "terminal_value"} & {
        node.node_id for node in operating.nodes
    }
    assert operating.historical_metrics.metrics
    selected = set(operating.selected_fact_ids)
    assert all(
        set(metric.fact_ids) <= selected
        for metric in operating.historical_metrics.metrics
    )
    assert (
        _prepare(operating_facts(), market_policy=_market_policy()).status
        == "abstained"
    )


def test_repeat_order_and_decimal_context_cannot_change_operating_identity():
    facts = operating_facts()
    first = prepare(facts)
    repeated = prepare(tuple(reversed(facts)))
    with localcontext() as context:
        context.prec = 7
        context.rounding = ROUND_DOWN
        constrained = prepare(facts)
        assert context.prec == 7 and context.rounding == ROUND_DOWN
    assert (
        canonical_bytes(first)
        == canonical_bytes(repeated)
        == canonical_bytes(constrained)
    )
    assert first.output_digest == sha256_digest(
        first.model_dump(exclude={"output_digest"})
    )


@pytest.mark.parametrize(
    "change",
    (
        {"mapping_version": "reviewed-mapping-v2"},
        {"policy_version": "operating-policy-v2"},
        {"model_version": "fcff_dcf-v2"},
        {"data_release_manifest_digest": "e" * 64},
    ),
)
def test_provenance_versions_are_part_of_both_identities(change):
    baseline = prepare(operating_facts())
    altered = prepare(operating_facts(), **change)
    assert baseline.input_digest != altered.input_digest
    assert baseline.output_digest != altered.output_digest
    assert baseline.nodes == altered.nodes


@pytest.mark.parametrize(
    "role", operating_forecast_requirements_profile("fcff_dcf").required_fact_fields
)
def test_each_required_operating_role_is_required_without_assumed_zero(role):
    facts = tuple(f for f in operating_facts() if f.normalized_field != role)
    result = prepare(facts)
    assert result.status == "abstained"
    assert role in result.missing_evidence
    assert not result.nodes and result.forecast is None


@pytest.mark.parametrize(
    "kind,expected",
    (
        ("foreign_issuer", "VALUATION_REQUIRED_FACTS_MISSING"),
        ("future_fact", "VALUATION_REQUIRED_FACTS_MISSING"),
        ("unapproved", "VALUATION_REQUIRED_FACTS_MISSING"),
        ("wrong_currency", "OPERATING_FACT_UNIT_INVALID"),
        ("shares_unit", "OPERATING_FACT_UNIT_INVALID"),
        ("future_source", "OPERATING_SOURCE_NOT_AVAILABLE"),
        ("dimension", "HISTORY_MINIMUM_PERIODS_UNAVAILABLE"),
        ("unknown_amendment", "FACT_AMENDMENT_SCOPE_UNKNOWN"),
    ),
)
def test_unusable_operating_evidence_is_retained_with_explicit_abstention(
    kind, expected
):
    changed = []
    for fact in operating_facts():
        if fact.normalized_field == "revenue":
            changes = {
                "foreign_issuer": {"issuer_id": "FOREIGN"},
                "future_fact": {"available_at": datetime(2027, 1, 1, tzinfo=UTC)},
                "unapproved": {"quality": QualityStatus.PROVISIONAL},
                "wrong_currency": {"currency": "EUR", "unit": "iso4217:EUR"},
                "shares_unit": {"unit": "xbrli:shares"},
                "future_source": {
                    "source": fact.source.model_copy(
                        update={"available_at": datetime(2027, 1, 1, tzinfo=UTC)}
                    )
                },
                "dimension": {
                    "context": fact.context.model_copy(
                        update={
                            "dimensions": (DimensionV1(name="Segment", member="One"),)
                        }
                    )
                },
                "unknown_amendment": {
                    "is_amendment": True,
                    "amendment_scope": "unknown",
                },
            }[kind]
            fact = fact.model_copy(update=changes)
        changed.append(fact)
    result = prepare(tuple(changed))
    assert result.status == "abstained"
    assert expected in result.issue_codes
    assert not result.nodes
    assert canonical_bytes(result) == canonical_bytes(prepare(tuple(reversed(changed))))


def test_same_id_changed_value_and_added_conflict_are_not_silently_selected():
    facts = operating_facts()
    revenue = next(
        f
        for f in facts
        if f.normalized_field == "revenue" and f.period_end.year == 2025
    )
    duplicate = revenue.model_copy(update={"value": Decimal("999")})
    assert "OPERATING_FACT_ID_DUPLICATE" in prepare((*facts, duplicate)).issue_codes
    conflict = duplicate.model_copy(update={"fact_id": "different-conflicting-revenue"})
    result = prepare((*facts, conflict))
    assert result.status == "abstained"
    assert "HISTORY_FACT_CONFLICT" in result.issue_codes
    changed = tuple(duplicate if f.fact_id == revenue.fact_id else f for f in facts)
    assert prepare(changed).input_digest != prepare(facts).input_digest


def test_rejected_input_contents_still_bind_research_input_identity():
    rejected = _fact("revenue", 2025, "999").model_copy(
        update={"issuer_id": "FOREIGN", "fact_id": "foreign"}
    )
    first = prepare((*operating_facts(), rejected))
    second = prepare(
        (*operating_facts(), rejected.model_copy(update={"value": Decimal("998")}))
    )
    assert first.status == second.status == "prepared"
    assert first.nodes == second.nodes
    assert first.rejected_fact_ids == ("foreign",)
    assert "VALUATION_FACT_CANDIDATES_REJECTED" in first.issue_codes
    assert first.input_digest != second.input_digest


def test_short_history_unstable_tax_and_extreme_growth_keep_refusals():
    facts = operating_facts()
    short = prepare(tuple(f for f in facts if f.period_end.year >= 2024))
    assert "HISTORY_MINIMUM_PERIODS_UNAVAILABLE" in short.issue_codes
    zero_tax_denominator = tuple(
        f.model_copy(update={"value": Decimal("0")})
        if f.normalized_field == "income_before_tax"
        else f
        for f in facts
    )
    assert (
        "METRIC_TAX_DENOMINATOR_UNSTABLE" in prepare(zero_tax_denominator).issue_codes
    )
    extreme = tuple(
        f.model_copy(update={"value": Decimal(100 ** (f.period_end.year - 2020))})
        if f.normalized_field == "revenue"
        else f
        for f in facts
    )
    assert "FORECAST_GROWTH_OUT_OF_BOUNDS" in prepare(extreme).issue_codes


def test_transition_retains_specific_filing_gate_and_unbound_evidence_refusal():
    assert (
        "filed_operating_evidence"
        in prepare(operating_facts(), model_id="transition_fcff_dcf").missing_evidence
    )
    filing = _fact("filed_operating_evidence", 2025, "1")
    filing = filing.model_copy(
        update={
            "source": filing.source.model_copy(update={"source_role": SourceRole.FACTS})
        }
    )
    result = prepare((*operating_facts(), filing), model_id="transition_fcff_dcf")
    assert "TRANSITION_EVIDENCE_INVALID" in result.issue_codes


def test_operating_contract_cannot_promote_quality_or_threshold():
    result = prepare(operating_facts())
    for changes in (
        {"quality_status": "verified"},
        {"supported_history_threshold": 3},
        {"status": "abstained"},
    ):
        payload = result.model_dump(mode="json")
        payload.update(changes)
        with pytest.raises(ValidationError):
            OperatingForecastV1.model_validate_json(json.dumps(payload))
    full = valuation_requirements_profile("fcff_dcf")
    assert len(full.required_fact_fields) == 32
    assert full.market_policy_input_roles


def test_period_misalignment_cannot_create_a_forecast():
    facts = tuple(
        fact.model_copy(update={"period_start": datetime(2025, 1, 2).date()})
        if fact.normalized_field == "operating_income" and fact.period_end.year == 2025
        else fact
        for fact in operating_facts()
    )
    result = prepare(facts)
    assert result.status == "abstained"
    assert "HISTORY_PERIOD_ALIGNMENT_CONFLICT" in result.issue_codes


def test_unbound_source_and_future_snapshot_source_cannot_supply_missing_role():
    facts = tuple(
        fact.model_copy(
            update={"source": fact.source.model_copy(update={"content_hash": "b" * 64})}
        )
        if fact.normalized_field == "revenue"
        else fact
        for fact in operating_facts()
    )
    assert "revenue" in prepare(facts).missing_evidence
    original = snapshot()
    changed = original.model_copy(
        update={
            "source_records": tuple(
                source.model_copy(
                    update={"available_at": datetime(2027, 1, 1, tzinfo=UTC)}
                )
                for source in original.source_records
            )
        }
    )
    assert prepare(operating_facts(), snapshot=changed).status == "abstained"


@pytest.mark.parametrize(
    "case,expected",
    (
        (
            "complete",
            "d73e001a62f1e9ea2119af0fc4b4197719a49732aaf037b401d9fff4a0b1c658",
        ),
        (
            "no_market",
            "031e492646af63c9a3028d8d9eec64712ac4be0787bfa3f1e14838ce8b29871e",
        ),
        (
            "missing_capital",
            "833075c6e50d768de97a7873b1f36994fd4bda09b65f0824d0bb3fe2abefe651",
        ),
        (
            "missing_annual",
            "aea9674bc5fabe9137f9f2114485652839a8909f09d1b395c5651e109e6bb931",
        ),
        (
            "insufficient_history",
            "1a6da5ae60552eac46dbb9a15e58e5235e384c5a535dbdac0b50d204fef78432",
        ),
        (
            "transition_no_evidence",
            "1544fbd2a3a25f756b7be574c9e926c3248e6edf52731e1eaa3ef826e410a658",
        ),
    ),
)
def test_full_valuation_preparation_matches_pre_extraction_digest(case, expected):
    facts = _facts()
    if case in {"missing_capital", "missing_annual"}:
        excluded = (
            "preferred_claims"
            if case == "missing_capital"
            else "stock_based_compensation"
        )
        facts = tuple(f for f in facts if f.normalized_field != excluded)
    if case == "insufficient_history":
        facts = tuple(f for f in facts if f.period_end.year >= 2024)
    result = _prepare(
        facts,
        market_policy=None if case == "no_market" else _market_policy(),
        model_id="transition_fcff_dcf"
        if case == "transition_no_evidence"
        else "fcff_dcf",
    )
    assert result.preparation_digest == expected
