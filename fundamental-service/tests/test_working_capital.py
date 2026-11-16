from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import SourceSnapshotV1, UncertaintyV1
from fundamental_service.calculator import calculate
from fundamental_service.operating_forecast import prepare_operating_forecast
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import (
    composite_working_capital_requirements_profile,
    operating_forecast_requirements_profile,
)
from fundamental_service.working_capital import (
    CompositeWorkingCapitalInputV1,
    InclusionScenariosV1,
    WorkingCapitalExclusionV1,
    assess_composite_working_capital,
    working_capital_policy_digest,
    canonical_working_capital_inputs,
)
from test_valuation_preparation import _fact, _facts as valuation_facts, _market_policy
from test_operating_forecast import operating_facts, snapshot
from equity_award_fixtures import award_evidence
from fundamental_service.valuation_preparation import prepare_automatic_valuation
from fundamental_service.working_capital import WORKING_CAPITAL_FIELDS

ACCESSION = "0000000001-25-000001"
SOURCE_HASH = "a" * 64
SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/1/fixture.htm"
SOURCE_TIME = datetime(2026, 1, 2, tzinfo=UTC)
VALUATION_TIME = datetime(2026, 3, 1, tzinfo=UTC)
PERIOD_END = datetime(2025, 12, 31).date()
MAPPING_VERSION = "reviewed-mapping-v1"


def _snapshot() -> SourceSnapshotV1:
    original = snapshot()
    source = original.source_records[0].model_copy(
        update={
            "uri": SOURCE_URL,
            "accession_number": ACCESSION,
            "available_at": SOURCE_TIME,
            "content_hash": SOURCE_HASH,
            "filing_version": "original",
        }
    )
    payload = original.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = (source,)
    return SourceSnapshotV1(
        **payload,
        manifest_digest=sha256_digest(
            {key: value for key, value in payload.items() if key != "snapshot_id"}
        ),
    )


def _fact_for(field: str, value: str, *, year: int = 2025, instant: bool = True):
    fact = _fact(field, year, value, instant=instant)
    provenance = fact.source.model_copy(
        update={
            "source_url": SOURCE_URL,
            "content_hash": SOURCE_HASH,
            "available_at": SOURCE_TIME,
            "captured_at": SOURCE_TIME,
            "filed_at": SOURCE_TIME,
            "accession_number": ACCESSION,
        }
    )
    return fact.model_copy(
        update={
            "security_id": None,
            "security_scope": "consolidated",
            "accession_number": ACCESSION,
            "filing_version": "original",
            "available_at": SOURCE_TIME,
            "filed_at": SOURCE_TIME,
            "captured_at": SOURCE_TIME,
            "mapping_decision_id": f"mapping-{field}",
            "mapping_confidence": "high",
            "source": provenance,
            "context": fact.context.model_copy(
                update={
                    "entity_scope": "consolidated",
                    "consolidation_scope": "consolidated",
                    "unit_qname": fact.unit,
                    "measure": fact.unit,
                }
            ),
        }
    )


def _scenarios(low: str, central: str, high: str, rationale: str):
    return InclusionScenariosV1(
        low=Decimal(low),
        central=Decimal(central),
        high=Decimal(high),
        rationale=rationale,
    )


def _input() -> CompositeWorkingCapitalInputV1:
    exclusions = (
        WorkingCapitalExclusionV1(
            account_class="cash_and_investments_combined",
            side="assets",
            state="reported",
            fact_id="cash_and_short_term_investments-2025",
            mapped_fact_role="cash_and_short_term_investments",
            covered_by_fact_id="current_assets-2025",
            covered_classes=("cash_and_equivalents", "short_term_investments"),
            rationale="Cash and short term investments are disclosed as one amount.",
        ),
        WorkingCapitalExclusionV1(
            account_class="current_interest_bearing_debt",
            side="liabilities",
            state="reported",
            fact_id="current_interest_bearing_debt-2025",
            mapped_fact_role="current_interest_bearing_debt",
            covered_by_fact_id="current_liabilities-2025",
            covered_classes=("current_interest_bearing_debt",),
            rationale="Current borrowings are separately reported within current liabilities.",
        ),
        *(
            WorkingCapitalExclusionV1(
                account_class=field,
                side="liabilities",
                state="reported",
                fact_id=f"{field}-2025",
                mapped_fact_role=field,
                covered_by_fact_id="current_liabilities-2025",
                covered_classes=(field,),
                rationale="Current lease financing is separately reported within current liabilities.",
            )
            for field in (
                "current_operating_lease_liabilities",
                "current_finance_lease_liabilities",
            )
        ),
    )
    return CompositeWorkingCapitalInputV1(
        policy_digest=working_capital_policy_digest(),
        mapping_version=MAPPING_VERSION,
        issuer_id="0000000001",
        accession_number=ACCESSION,
        source_hash=SOURCE_HASH,
        period_end=PERIOD_END,
        current_assets_fact_id="current_assets-2025",
        current_liabilities_fact_id="current_liabilities-2025",
        exclusions=exclusions,
        asset_residual=_scenarios(
            "0.4", "0.6", "0.8", "Issuer-specific asset residual inclusion scenarios."
        ),
        liability_residual=_scenarios(
            "0.4",
            "0.5",
            "0.6",
            "Issuer-specific liability residual inclusion scenarios.",
        ),
        perimeter_rationale="Gross totals and excluded classes share a consolidated filing perimeter.",
    )


def _facts():
    return (
        _fact_for("current_assets", "100"),
        _fact_for("current_liabilities", "40"),
        _fact_for("cash_and_short_term_investments", "15"),
        _fact_for("current_interest_bearing_debt", "5"),
        _fact_for("current_operating_lease_liabilities", "2"),
        _fact_for("current_finance_lease_liabilities", "1"),
    )


def test_composite_assessment_is_source_bound_and_deterministic():
    policy, facts, source = _input(), _facts(), _snapshot()
    result = assess_composite_working_capital(policy, facts, snapshot=source)
    repeated = assess_composite_working_capital(
        policy, tuple(reversed(facts)), snapshot=source
    )

    assert result.status == "estimated", result.missing_evidence
    assert result.value == Decimal("35.0")
    assert result.adjusted_assets == Decimal("85")
    assert result.adjusted_liabilities == Decimal("32")
    assert result.policy_digest == working_capital_policy_digest()
    assert (
        result.sensitivity_interpretation
        == "deterministic_scenarios_not_confidence_intervals"
    )
    assert {fact.fact_id for fact in result.source_facts} == set(policy.fact_ids)
    assert result.output_digest == repeated.output_digest
    assert canonical_bytes(result) == canonical_bytes(repeated)


@pytest.mark.parametrize("version", ["original", ACCESSION])
def test_original_source_versions_and_compatible_issuer_scopes_share_one_assessment(
    version,
):
    source = _snapshot()
    record = source.source_records[0].model_copy(update={"filing_version": version})
    source = source.model_copy(update={"source_records": (record,)})
    scopes = ("unspecified", "issuer", "consolidated")
    facts = tuple(
        fact.model_copy(
            update={"filing_version": version, "security_scope": scopes[i % 3]}
        )
        for i, fact in enumerate(_facts())
    )
    result = assess_composite_working_capital(_input(), facts, snapshot=source)
    assert result.status == "estimated", result.missing_evidence
    assert result.value == Decimal("35.0")
    assert result.source_facts == tuple(
        sorted(facts, key=lambda f: (f.fact_id, sha256_digest(f)))
    )


@pytest.mark.parametrize(
    "case",
    [
        "version_mismatch",
        "unknown_version",
        "missing_version",
        "amended_form",
        "source_amendment",
        "fact_amendment",
        "source_link",
        "fact_link",
    ],
)
def test_original_version_checks_retain_amendment_and_version_refusals(case):
    source = _snapshot()
    record = source.source_records[0]
    facts = list(_facts())
    source_changes = {}
    fact_changes = {}
    if case in {"version_mismatch", "unknown_version", "missing_version"}:
        source_changes["filing_version"] = {
            "version_mismatch": ACCESSION,
            "unknown_version": "unresolved",
            "missing_version": None,
        }[case]
        if case != "version_mismatch":
            fact_changes["filing_version"] = source_changes["filing_version"]
    elif case == "amended_form":
        source_changes["form"] = "10-K/A"
    elif case == "source_amendment":
        source_changes["is_amendment"] = True
    elif case == "fact_amendment":
        fact_changes["is_amendment"] = True
    elif case == "source_link":
        source_changes["amends_accession"] = ACCESSION
    else:
        fact_changes["amends_accession"] = ACCESSION
    source = source.model_copy(
        update={"source_records": (record.model_copy(update=source_changes),)}
    )
    facts[0] = facts[0].model_copy(update=fact_changes)
    result = assess_composite_working_capital(_input(), tuple(facts), snapshot=source)
    assert result.status == "abstained" and result.value is None
    reason = "FILING_VERSION" if "version" in case else "AMENDMENT"
    assert any(item.endswith(":" + reason) for item in result.missing_evidence)


@pytest.mark.parametrize("scope", ["segmented", "unknown", "security"])
def test_segmented_unknown_and_unbacked_security_scopes_abstain(scope):
    facts = list(_facts())
    facts[0] = facts[0].model_copy(update={"security_scope": scope})
    result = assess_composite_working_capital(
        _input(), tuple(facts), snapshot=_snapshot()
    )
    assert result.status == "abstained" and result.value is None
    assert any(item.endswith(":SECURITY_SCOPE") for item in result.missing_evidence)


def test_unknown_exclusion_abstains_without_turning_unknown_into_zero():
    policy = _input()
    exclusions = tuple(
        item.model_dump() | {"state": "unknown", "fact_id": None}
        if item.account_class == "cash_and_investments_combined"
        else item.model_dump()
        for item in policy.exclusions
    )
    policy = CompositeWorkingCapitalInputV1.model_validate(
        policy.model_dump() | {"exclusions": exclusions}
    )
    result = assess_composite_working_capital(policy, _facts(), snapshot=_snapshot())
    assert result.status == "abstained"
    assert result.value is None
    assert result.sensitivity == ()
    assert (
        "WORKING_CAPITAL_EXCLUSION_UNKNOWN:cash_and_investments_combined"
        in result.missing_evidence
    )


@pytest.mark.parametrize(
    "field,update,reason",
    (
        (
            "accession_number",
            "0000000001-25-000999",
            "WORKING_CAPITAL_SOURCE_SCOPE_INVALID",
        ),
        ("amendment_scope", "unknown", "WORKING_CAPITAL_SOURCE_SCOPE_INVALID"),
        ("filing_version", "amendment", "WORKING_CAPITAL_SOURCE_SCOPE_INVALID"),
        ("unit", "shares", "WORKING_CAPITAL_UNIT_MISMATCH"),
        (
            "available_at",
            datetime(2026, 4, 1, tzinfo=UTC),
            "WORKING_CAPITAL_SOURCE_SCOPE_INVALID",
        ),
    ),
)
def test_source_scope_unit_and_availability_mismatches_abstain(field, update, reason):
    facts = list(_facts())
    change = {field: update}
    if field == "available_at":
        change.update({"filed_at": update, "captured_at": update})
        change["source"] = facts[0].source.model_copy(
            update={"available_at": update, "filed_at": update, "captured_at": update}
        )
    facts[0] = facts[0].model_copy(update=change)
    result = assess_composite_working_capital(
        _input(), tuple(facts), snapshot=_snapshot()
    )
    assert result.status == "abstained"
    assert result.value is None
    assert any(item.startswith(reason) for item in result.missing_evidence)


def test_duplicate_fact_id_and_policy_digest_mismatch_abstain():
    facts = (*_facts(), _facts()[0])
    duplicate = assess_composite_working_capital(_input(), facts, snapshot=_snapshot())
    assert duplicate.status == "abstained"
    assert "WORKING_CAPITAL_FACT_ID_DUPLICATE" in duplicate.missing_evidence

    policy = _input().model_copy(update={"policy_digest": "0" * 64})
    mismatch = assess_composite_working_capital(policy, _facts(), snapshot=_snapshot())
    assert mismatch.status == "abstained"
    assert "WORKING_CAPITAL_POLICY_DIGEST_MISMATCH" in mismatch.missing_evidence


def test_overlapping_component_coverage_is_rejected():
    policy = _input()
    exclusions = tuple(
        item.model_dump()
        | {
            "covered_classes": (
                "current_finance_lease_liabilities",
                "current_interest_bearing_debt",
            )
        }
        if item.account_class == "current_interest_bearing_debt"
        else item.model_dump()
        for item in policy.exclusions
    )
    with pytest.raises(ValidationError, match="coverage must not overlap"):
        CompositeWorkingCapitalInputV1.model_validate(
            policy.model_dump() | {"exclusions": exclusions}
        )


def test_estimated_route_is_a_distinct_profile_and_keeps_threshold_null():
    exact = operating_forecast_requirements_profile("fcff_dcf")
    estimated = composite_working_capital_requirements_profile("fcff_dcf")
    assert exact.profile_version == "operating-forecast-requirements-v1"
    assert estimated.profile_version == "composite-noncash-working-capital-v3"
    assert "operating_current_receivables" in exact.required_fact_fields
    assert "operating_current_receivables" not in estimated.required_fact_fields
    assert "current_assets" in estimated.required_fact_fields
    assert estimated.supported_history_threshold is None


def _composite_history():
    source = _snapshot()
    base = []
    for fact in operating_facts():
        if fact.normalized_field in {
            "operating_current_receivables",
            "inventory",
            "contract_assets",
            "operating_current_payables",
            "accrued_operating_liabilities",
            "deferred_revenue",
        }:
            continue
        provenance = fact.source.model_copy(
            update={
                "source_url": SOURCE_URL,
                "content_hash": SOURCE_HASH,
                "available_at": SOURCE_TIME,
                "captured_at": SOURCE_TIME,
                "filed_at": SOURCE_TIME,
                "accession_number": ACCESSION,
            }
        )
        base.append(
            fact.model_copy(
                update={
                    "accession_number": ACCESSION,
                    "filing_version": "original",
                    "available_at": SOURCE_TIME,
                    "filed_at": SOURCE_TIME,
                    "captured_at": SOURCE_TIME,
                    "mapping_decision_id": f"mapping-{fact.normalized_field}",
                    "mapping_confidence": "high",
                    "source": provenance,
                }
            )
        )

    extra_facts = []
    inputs = []
    for year in range(2021, 2026):
        end = datetime(year, 12, 31).date()
        extra_facts.extend(
            (
                _fact_for("current_assets", "100", year=year),
                _fact_for("current_liabilities", "40", year=year),
                _fact_for("cash_and_short_term_investments", "15", year=year),
                _fact_for("current_interest_bearing_debt", "5", year=year),
                _fact_for("current_operating_lease_liabilities", "2", year=year),
                _fact_for("current_finance_lease_liabilities", "1", year=year),
            )
        )
        template = _input()
        inputs.append(
            CompositeWorkingCapitalInputV1.model_validate(
                template.model_dump()
                | {
                    "period_end": end,
                    "current_assets_fact_id": f"current_assets-{year}",
                    "current_liabilities_fact_id": f"current_liabilities-{year}",
                    "exclusions": tuple(
                        item.model_dump()
                        | {
                            "fact_id": f"{item.mapped_fact_role}-{year}",
                            "covered_by_fact_id": (
                                f"current_assets-{year}"
                                if item.side == "assets"
                                else f"current_liabilities-{year}"
                            ),
                        }
                        for item in template.exclusions
                    ),
                }
            )
        )

    return source, tuple(base + extra_facts), tuple(inputs)


def test_two_model_service_composer_accepts_versioned_composite_inputs():
    source, facts, inputs = _composite_history()
    for model_id in ("fcff_dcf", "transition_fcff_dcf"):
        composer_facts = list(facts)
        if model_id == "transition_fcff_dcf":
            filed = _fact("filed_operating_evidence", 2025, "1").model_copy(
                update={"value": "retained original transition evidence"}
            )
            provenance = filed.source.model_copy(
                update={
                    "source_url": SOURCE_URL,
                    "content_hash": SOURCE_HASH,
                    "available_at": SOURCE_TIME,
                    "captured_at": SOURCE_TIME,
                    "filed_at": SOURCE_TIME,
                    "accession_number": ACCESSION,
                }
            )
            composer_facts.append(
                filed.model_copy(
                    update={
                        "accession_number": ACCESSION,
                        "filing_version": "original",
                        "available_at": SOURCE_TIME,
                        "filed_at": SOURCE_TIME,
                        "captured_at": SOURCE_TIME,
                        "source": provenance,
                    }
                )
            )
        result = prepare_operating_forecast(
            tuple(composer_facts),
            snapshot=source,
            model_id=model_id,
            model_version=f"{model_id}-v2",
            policy_id=f"{model_id}-policy-v2",
            policy_version="policy-v2",
            mapping_version=MAPPING_VERSION,
            data_release_manifest_digest="d" * 64,
            working_capital_inputs=tuple(inputs),
        )
        assert result.status == "prepared"
        assert result.quality_status.value == "provisional"
        assert result.supported_history_threshold is None
        assert "WORKING_CAPITAL_INPUT_ESTIMATED" in result.issue_codes
        assert (
            result.historical_metrics.working_capital_inputs
            == canonical_working_capital_inputs(tuple(inputs))
        )
        assert all(
            set(metric.fact_ids) <= set(result.selected_fact_ids)
            for metric in result.historical_metrics.metrics
        )
        repeated = prepare_operating_forecast(
            tuple(reversed(composer_facts)),
            snapshot=source,
            model_id=model_id,
            model_version=f"{model_id}-v2",
            policy_id=f"{model_id}-policy-v2",
            policy_version="policy-v2",
            mapping_version=MAPPING_VERSION,
            data_release_manifest_digest="d" * 64,
            working_capital_inputs=tuple(reversed(inputs)),
        )
        assert canonical_bytes(result) == canonical_bytes(repeated)


def test_full_valuation_reuses_composite_facts_without_duplicating_capital_bridge():
    source, facts, inputs = _composite_history()
    # The latest current-debt/lease facts serve both the annual input and bridge.
    by_id = {fact.fact_id: fact for fact in facts}
    for fact in valuation_facts():
        if fact.normalized_field in WORKING_CAPITAL_FIELDS or fact.fact_id in by_id:
            continue
        by_id[fact.fact_id] = _fact_for(
            fact.normalized_field,
            str(fact.value),
            year=fact.period_end.year,
            instant=fact.instant is not None,
        )
    dilution = award_evidence(source)
    released = (*by_id.values(), *dilution.facts)
    kwargs = dict(
        snapshot=source,
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        policy_id="fcff_dcf-us-gaap-public-v2",
        policy_version="fcff_dcf-v2-quality-v1",
        data_release_manifest_digest="d" * 64,
        market_policy=_market_policy(),
        mapping_version=MAPPING_VERSION,
        equity_dilution_evidence=dilution,
        working_capital_inputs=inputs,
    )
    result = prepare_automatic_valuation(released, **kwargs)
    assert result.input is not None, (result.issue_codes, result.missing_evidence)
    assert result.quality_status.value == "provisional"
    assert (
        result.historical_metrics.working_capital_inputs
        == canonical_working_capital_inputs(inputs)
    )
    assert result.input.assumptions.forecast is not None
    operating = prepare_operating_forecast(
        facts,
        **{
            key: value
            for key, value in kwargs.items()
            if key not in {"market_policy", "equity_dilution_evidence"}
        },
    )
    calculated = calculate(
        result.input.model_copy(
            update={"uncertainty": UncertaintyV1(mode="none")}
        ).with_digest(),
        allow_provisional=True,
    )
    assert {node.node_id: node.value for node in operating.nodes[1:]} == {
        node.node_id: node.value
        for node in calculated.nodes
        if node.node_id.startswith(("revenue_", "fcff_"))
    }
    assert canonical_bytes(result) == canonical_bytes(
        prepare_automatic_valuation(tuple(reversed(released)), **kwargs)
    )
    blocked = prepare_automatic_valuation(
        released, **(kwargs | {"market_policy": None})
    )
    assert blocked.input is None
    assert "MARKET_POLICY_INPUTS_MISSING" in blocked.issue_codes
    assert blocked.historical_metrics.working_capital_inputs
