from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fundamental_service.application.service import _approved_market_policy
from fundamental_service.contracts import (
    IdentityV1,
    PeriodType,
    QualityStatus,
    SourceRole,
    TraceV1,
)
from fundamental_service.policies import initial_policy_records
from fundamental_service.valuation_preparation import (
    ApprovedMarketPolicyInputsV1,
    ManualProvenanceV1,
    PreparationError,
    apply_manual_override,
    prepare_automatic_valuation,
)
from fundamental_service.valuation_requirements import (
    select_released_facts,
    valuation_requirements_profile,
)
from test_api import _canonical_fact
from test_postgres_metadata import _snapshot

VALUATION_TIME = datetime(2026, 3, 1, tzinfo=UTC)
RELEASE_DIGEST = "d" * 64


def _fact(
    field: str,
    year: int,
    value: str,
    *,
    instant: bool = False,
    fact_id: str | None = None,
    available_at: datetime | None = None,
):
    period_start = None if instant else datetime(year, 1, 1).date()
    period_end = datetime(year, 12, 31).date()
    base = _canonical_fact(fact_id or f"{field}-{year}", field)
    return base.model_copy(
        update={
            "concept": f"us-gaap:{field}",
            "value": Decimal(value),
            "period_start": period_start,
            "period_end": period_end,
            "instant": period_end if instant else None,
            "available_at": available_at or datetime(year + 1, 2, 1, tzinfo=UTC),
            "filed_at": available_at or datetime(year + 1, 2, 1, tzinfo=UTC),
            "as_of": datetime(year, 12, 31, tzinfo=UTC),
            "context": base.context.model_copy(
                update={
                    "concept_qname": f"us-gaap:{field}",
                    "period_type": PeriodType.INSTANT
                    if instant
                    else PeriodType.DURATION,
                    "start_date": period_start,
                    "end_date": None if instant else period_end,
                    "instant": period_end if instant else None,
                }
            ),
        }
    )


def _facts() -> tuple:
    duration_fields = (
        "revenue",
        "cost_of_revenue",
        "operating_income",
        "income_before_tax",
        "income_tax_expense",
        "net_income",
        "depreciation_and_amortization",
        "capital_expenditure",
        "operating_lease_cost",
        "finance_lease_cost",
        "stock_based_compensation",
        "basic_weighted_average_shares",
        "diluted_weighted_average_shares",
    )
    instant_fields = (
        "operating_current_receivables",
        "inventory",
        "contract_assets",
        "operating_current_payables",
        "accrued_operating_liabilities",
        "deferred_revenue",
    )
    point_fields = (
        "cash_and_equivalents",
        "current_interest_bearing_debt",
        "long_term_interest_bearing_debt",
        "current_operating_lease_liabilities",
        "long_term_operating_lease_liabilities",
        "current_finance_lease_liabilities",
        "long_term_finance_lease_liabilities",
        "preferred_claims",
        "noncontrolling_interests",
        "convertible_instruments",
        "common_shares_outstanding",
        "dilutive_instruments",
        "other_share_classes",
    )
    facts = []
    for year in range(2021, 2026):
        revenue = Decimal(100 + (year - 2021) * 10)
        values = {
            "revenue": revenue,
            "operating_income": revenue * Decimal("0.2"),
            "income_before_tax": revenue * Decimal("0.25"),
            "income_tax_expense": revenue * Decimal("0.05"),
            "capital_expenditure": Decimal("10"),
            "depreciation_and_amortization": Decimal("4"),
            "operating_current_receivables": Decimal(10 + year - 2021),
            "inventory": Decimal(5 + year - 2021),
            "contract_assets": Decimal(2 + year - 2021),
            "operating_current_payables": Decimal(8 + year - 2021),
            "accrued_operating_liabilities": Decimal(2 + year - 2021),
            "deferred_revenue": Decimal(1 + year - 2021),
        }
        for field in duration_fields:
            facts.append(_fact(field, year, str(values.get(field, Decimal("1")))))
        for field in instant_fields:
            facts.append(_fact(field, year, str(values[field]), instant=True))
    for field in point_fields:
        facts.append(
            _fact(field, 2025, "10" if "shares" not in field else "100", instant=True)
        )
    return tuple(facts)


def _market_policy() -> ApprovedMarketPolicyInputsV1:
    evidence = {
        field: TraceV1(description=f"approved {field}")
        for field in (
            "risk_free_rate",
            "beta",
            "equity_risk_premium",
            "pre_tax_cost_of_debt",
            "debt_weight",
            "equity_weight",
            "terminal_growth",
        )
    }
    return ApprovedMarketPolicyInputsV1(
        policy_version="market-policy-v1",
        risk_free_rate=Decimal("0.04"),
        beta=Decimal("1.1"),
        equity_risk_premium=Decimal("0.05"),
        pre_tax_cost_of_debt=Decimal("0.05"),
        debt_weight=Decimal("0.2"),
        equity_weight=Decimal("0.8"),
        terminal_growth=Decimal("0.02"),
        evidence=evidence,
    )


def _prepare(
    facts: tuple,
    *,
    market_policy=None,
    model_id: str = "fcff_dcf",
):
    return prepare_automatic_valuation(
        facts,
        snapshot=_snapshot(
            "valuation-preparation",
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
        ),
        model_id=model_id,
        model_version=f"{model_id}-v1",
        policy_id="fcff_dcf-us-gaap-public-v1",
        policy_version="fcff_dcf-v1-quality-v1",
        data_release_manifest_digest=RELEASE_DIGEST,
        market_policy=market_policy,
    )


def test_complete_history_prepares_provisional_input_with_lineage_and_digest() -> None:
    result = _prepare(_facts(), market_policy=_market_policy())

    assert result.status == "prepared"
    assert result.quality_status is QualityStatus.PROVISIONAL
    assert result.input is not None
    assert result.input.valuation_context.data_release_manifest_digest == RELEASE_DIGEST
    assert len(result.input.assumptions.forecast.revenue_growth) == 5
    growth_evidence = tuple(
        item
        for item in result.assumptions_evidence
        if item.path.startswith("assumptions.forecast.revenue_growth[")
    )
    assert len(growth_evidence) == 5
    assert all(item.fact_ids and item.formula for item in growth_evidence)
    assert any(
        item.metric_id == "reinvestment_rate"
        for item in result.historical_metrics.metrics
    )
    assert (
        result.preparation_digest
        == _prepare(_facts(), market_policy=_market_policy()).preparation_digest
    )


def test_released_market_policy_prepares_without_caller_assumptions() -> None:
    policy = initial_policy_records()[0]
    market_policy = _approved_market_policy(
        policy,
        valuation_timestamp=VALUATION_TIME,
    )

    result = _prepare(_facts(), market_policy=market_policy)

    assert result.status == "prepared"
    assert result.input is not None
    risk_free = next(
        item
        for item in result.assumptions_evidence
        if item.path == "assumptions.wacc.risk_free_rate"
    )
    assert risk_free.source_refs == (
        "1cf8c2d38f773142b58b772bde5028d12f00dfd72bf37b40c2327e15d418ea28",
    )
    assert risk_free.as_of == datetime(2025, 1, 3, tzinfo=UTC)
    assert risk_free.method == "approved_source"
    assert (
        next(
            item
            for item in result.assumptions_evidence
            if item.path == "assumptions.wacc.debt_weight"
        ).method
        == "approved_policy"
    )


def test_missing_market_policy_requires_input_without_default_values() -> None:
    result = _prepare(_facts())

    assert result.status == "requires_input"
    assert result.input is None
    assert "MARKET_POLICY_INPUTS_MISSING" in result.issue_codes
    assert "approved_market_policy_inputs" in result.missing_evidence


def test_insufficient_contiguous_history_abstains() -> None:
    facts = tuple(
        fact
        for fact in _facts()
        if not (
            fact.normalized_field == "operating_income" and fact.period_end.year == 2024
        )
    )

    result = _prepare(facts, market_policy=_market_policy())

    assert result.status == "abstained"
    assert result.quality_status is QualityStatus.ABSTAIN
    assert "HISTORY_MINIMUM_PERIODS_UNAVAILABLE" in result.issue_codes


def test_point_in_time_conflict_abstains_instead_of_picking_a_winner() -> None:
    duplicate = _fact(
        "cash_and_equivalents",
        2025,
        "999",
        instant=True,
        fact_id="cash-conflict",
    )

    result = _prepare((*_facts(), duplicate), market_policy=_market_policy())

    assert result.status == "abstained"
    assert "CAPITAL_FACT_CONFLICT" in result.issue_codes


def test_transition_filing_evidence_can_be_non_numeric_but_remains_release_bound() -> (
    None
):
    profile = valuation_requirements_profile("transition_fcff_dcf")
    filing = _fact("filed_operating_evidence", 2025, "1").model_copy(
        update={"value": "filed evidence"}
    )
    selection = select_released_facts(
        (*_facts(), filing),
        profile=profile,
        snapshot=_snapshot(
            "transition-evidence",
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
        ),
        valuation_timestamp=VALUATION_TIME,
    )

    assert filing.fact_id not in selection.rejected_fact_ids
    assert filing in selection.facts


def test_transition_preparation_requires_valid_filed_evidence() -> None:
    filing = _fact("filed_operating_evidence", 2025, "1").model_copy(
        update={"value": "filed evidence"}
    )

    result = _prepare(
        (*_facts(), filing),
        market_policy=_market_policy(),
        model_id="transition_fcff_dcf",
    )

    assert result.status == "prepared"
    assert result.input is not None
    assert filing.fact_id in result.input.assumptions.trace.inputs
    assert (
        "pinned transition filing evidence"
        in result.input.assumptions.trace.description
    )


def test_transition_preparation_abstains_on_unbound_filing_evidence() -> None:
    filing = _fact("filed_operating_evidence", 2025, "1").model_copy(
        update={
            "value": "filed evidence",
            "source": _fact("filed_operating_evidence", 2025, "1").source.model_copy(
                update={"source_role": SourceRole.FACTS}
            ),
        }
    )

    result = _prepare(
        (*_facts(), filing),
        market_policy=_market_policy(),
        model_id="transition_fcff_dcf",
    )

    assert result.status == "abstained"
    assert result.quality_status is QualityStatus.ABSTAIN
    assert "TRANSITION_EVIDENCE_INVALID" in result.issue_codes


def test_manual_override_preserves_automatic_evidence_and_changes_digests() -> None:
    automatic = _prepare(_facts(), market_policy=_market_policy())
    path = "assumptions.forecast.operating_margin[0]"
    provenance = ManualProvenanceV1(
        author="reviewer-1",
        modified_at=datetime(2026, 3, 2, tzinfo=UTC),
        reason="approved normalization adjustment",
        automatic_preparation_digest=automatic.preparation_digest,
    )

    overridden = apply_manual_override(
        automatic,
        path=path,
        value=Decimal("0.24"),
        provenance=provenance,
    )

    assert overridden.input is not None
    assert overridden.input.assumptions.forecast.operating_margin[0] == Decimal("0.24")
    assert overridden.input.input_digest != automatic.input.input_digest
    assert overridden.preparation_digest != automatic.preparation_digest
    assert any(
        item.path == path and item.method == "derived"
        for item in overridden.assumptions_evidence
    )
    manual = tuple(
        item for item in overridden.assumptions_evidence if item.method == "manual"
    )
    assert len(manual) == 1
    assert manual[0].manual_provenance == provenance
    assert "MANUAL_OVERRIDE_APPLIED" in overridden.issue_codes


def test_manual_override_rejects_wrong_automatic_digest_or_unsupported_path() -> None:
    automatic = _prepare(_facts(), market_policy=_market_policy())
    provenance = ManualProvenanceV1(
        author="reviewer-1",
        modified_at=datetime(2026, 3, 2, tzinfo=UTC),
        reason="approved adjustment",
        automatic_preparation_digest="f" * 64,
    )

    with pytest.raises(PreparationError, match="different automatic preparation"):
        apply_manual_override(
            automatic,
            path="assumptions.terminal_growth",
            value=Decimal("0.02"),
            provenance=provenance,
        )

    valid_provenance = provenance.model_copy(
        update={"automatic_preparation_digest": automatic.preparation_digest}
    )
    with pytest.raises(PreparationError, match="no unique automatic evidence"):
        apply_manual_override(
            automatic,
            path="assumptions.trace.description",
            value=Decimal("1"),
            provenance=valid_provenance,
        )
