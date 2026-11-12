"""Scenarios conserve source parents and cannot authorize an exact forecast."""

from datetime import date
from decimal import Context, Decimal, ROUND_DOWN, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.annual_history import AnnualHistoryPeriodV1, AnnualHistoryV1
from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.contracts import QualityStatus
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.operating_scenario_runner import publish_scenario_replay
from fundamental_service.operating_scenario_contracts import (
    CORE_FIELDS,
    PARENT_CONCEPTS,
    UNRESOLVED_CLASSES,
    OperatingScenarioRequestV1,
    OperatingScenarioV1,
    ParentPartitionV1,
    ScenarioPeriodV1,
    scenario_policy_digest,
)
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.operating_projection import project_operating_nodes
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_preparation import (
    compose_forecast_assumptions,
    derive_historical_metrics,
)
from test_original_issuer import DECISION, original
from test_valuation_preparation import _fact


def request(*, parent_assets="200", cash="50", second_revenue=None):
    report, source = original()
    concepts = {**{role: f"us-gaap:{role}" for role in CORE_FIELDS}, **PARENT_CONCEPTS}
    mappings = tuple(
        sorted(
            (
                CanonicalMappingV1(
                    contract_version="fundamental.v1",
                    decision_id=f"mapping-{role}",
                    source_concept=concept,
                    normalized_field=role,
                    mapping_version="scenario-test-v1",
                    confidence="unresolved",
                    status="provisional",
                )
                for role, concept in concepts.items()
            ),
            key=lambda mapping: mapping.decision_id,
        )
    )
    raw = list(report.facts)
    for year in (2023, 2024, 2025):
        revenue = 1000 + 100 * (year - 2023)
        values = {
            "revenue": revenue,
            "operating_income": 100,
            "income_before_tax": 100,
            "income_tax_expense": 25,
            "depreciation_and_amortization": 10,
            "capital_expenditure": 20,
            "current_assets": parent_assets,
            "current_liabilities": 70,
            "cash_and_equivalents": cash,
        }
        for role, concept in concepts.items():
            instant = role in {
                "current_assets",
                "current_liabilities",
                "cash_and_equivalents",
            }
            raw.append(
                ParsedXbrlFactV1(
                    concept=concept,
                    namespace_uri="http://fasb.org/us-gaap/2015-01-31",
                    context_id=f"{role}-{year}",
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier=source.cik,
                    value=str(values[role]),
                    unit="iso4217:USD",
                    is_numeric=True,
                    decimals="0",
                    consolidation_scope="consolidated",
                    security_scope="unspecified",
                    period_start=None if instant else date(year, 1, 1),
                    period_end=None if instant else date(year, 12, 31),
                    instant=date(year, 12, 31) if instant else None,
                )
            )
    if second_revenue is not None:
        revenue = next(fact for fact in raw if fact.context_id == "revenue-2023")
        raw.append(
            revenue.model_copy(
                update={"context_id": "competing-revenue", "value": second_revenue}
            )
        )
    report = report.model_copy(update={"facts": tuple(raw)})
    evidence = evaluate_original_issuer(report, source=source, decision_at=DECISION)
    snapshot = compose_issuer_operating_source(
        (evidence,), valuation_timestamp=DECISION
    )
    facts = tuple(
        candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
        for mapping in mappings
        for candidate in parsed_facts_to_candidates(
            report,
            source=source,
            issuer_id=source.cik,
            normalized_field=mapping.normalized_field,
            mapping=mapping,
        )
    )
    periods = tuple(
        ScenarioPeriodV1(
            fiscal_year=year,
            period_start=date(year, 1, 1),
            period_end=date(year, 12, 31),
            fact_ids={
                fact.normalized_field: fact.fact_id
                for fact in facts
                if fact.period_end.year == year
            },
        )
        for year in (2023, 2024, 2025)
    )
    scenario = OperatingScenarioV1(
        scenario_id="all-operating-residual",
        operating_asset_fraction=Decimal(1),
        operating_liability_fraction=Decimal(1),
        continuing_capex_fractions={year: Decimal(1) for year in (2023, 2024, 2025)},
        rationale="An explicit hypothetical full-residual allocation, not a classification fact.",
    )
    return OperatingScenarioRequestV1(
        source=snapshot,
        facts=facts,
        periods=periods,
        scenarios=(scenario,),
        mapping_version="scenario-test-v1",
        mappings=mappings,
        mapping_manifest_digest=sha256_digest(mappings),
        protocol_version="prospective-fixture-grid-v1",
        policy_digest=scenario_policy_digest(),
        model_versions={
            "fcff_dcf": "fcff_dcf-v2",
            "transition_fcff_dcf": "transition_fcff_dcf-v2",
        },
        scope_assumption_evidence_digests=("f" * 64,),
        unresolved_classes=UNRESOLVED_CLASSES,
    )


def test_real_mapper_source_values_remain_immutable_and_scenario_matches_exact_metrics():
    req = request()
    before = canonical_bytes(req)
    result = replay_operating_scenarios(req)
    scenario, transition = result.results
    assert scenario.status == "provisional_scenario"
    assert (
        transition.status == "abstained"
        and "TRANSITION_EVIDENCE_MISSING" in transition.issue_codes
    )
    assert canonical_bytes(req) == before
    assert all(fact.quality is QualityStatus.PROVISIONAL for fact in req.facts)
    assert (
        scenario.supported_history_threshold
        is result.supported_history_threshold
        is None
    )
    assert result.bounds_claim == "sampled_scenarios_only"
    exact_periods = []
    for period in req.periods:
        selected = {
            fact.normalized_field: fact
            for fact in req.facts
            if fact.fact_id in period.fact_ids.values()
        }
        exact_periods.append(
            AnnualHistoryPeriodV1(
                fiscal_year=period.fiscal_year,
                period_start=period.period_start,
                period_end=period.period_end,
                duration_facts=tuple(
                    selected[role] for role in (*CORE_FIELDS, "capital_expenditure")
                ),
                instant_facts=tuple(
                    _fact(role, period.fiscal_year, value, instant=True)
                    for role, value in (
                        ("operating_current_receivables", "150"),
                        ("inventory", "0"),
                        ("contract_assets", "0"),
                        ("operating_current_payables", "70"),
                        ("accrued_operating_liabilities", "0"),
                        ("deferred_revenue", "0"),
                    )
                ),
            )
        )
    history = AnnualHistoryV1(
        requirements_profile_id="exact-test",
        requirements_profile_digest="e" * 64,
        requested_fiscal_years=(2025, 2024, 2023),
        periods=tuple(exact_periods),
        missing_fields=(),
        quality=QualityStatus.PROVISIONAL,
        issue_codes=(),
    )
    metrics = derive_historical_metrics(history)
    forecast = compose_forecast_assumptions(history, metrics)
    assert scenario.forecast == forecast
    assert scenario.historical_metrics is not None
    assert [
        (item.metric_id, item.fiscal_year, item.value)
        for item in scenario.historical_metrics.metrics
    ] == [(item.metric_id, item.fiscal_year, item.value) for item in metrics.metrics]
    expected_nodes = project_operating_nodes(
        forecast, tax_rate=Decimal("0.25"), historical_fact_ids=scenario.nodes[0].inputs
    )
    assert scenario.nodes == expected_nodes
    assert all(
        set(metric.fact_ids) <= set(result.retained_fact_ids)
        for metric in scenario.historical_metrics.metrics
    )


def test_joint_partition_keeps_unknown_categories_and_never_double_counts():
    req = request()
    scenario = req.scenarios[0].model_copy(
        update={
            "operating_asset_fraction": Decimal("0.25"),
            "operating_liability_fraction": Decimal("0.75"),
            "continuing_capex_fractions": {
                year: Decimal("0.5") for year in (2023, 2024, 2025)
            },
        }
    )
    result = replay_operating_scenarios(
        req.model_copy(update={"scenarios": (scenario,)})
    ).results[0]
    period = result.period_inputs[0]
    assert period.assets.known_excluded == 50
    assert period.assets.operating == Decimal("37.5")
    assert period.assets.unresolved_excluded == Decimal("112.5")
    assert period.liabilities.operating == Decimal("52.5")
    assert period.capex.operating == period.capex.unresolved_excluded == 10
    assert period.operating_working_capital == -15
    assert req.unresolved_classes == UNRESOLVED_CLASSES
    with pytest.raises(ValidationError, match="conserve"):
        ParentPartitionV1.model_validate(
            {**period.assets.model_dump(), "operating": Decimal(100)}
        )


@pytest.mark.parametrize(
    "kind,code",
    (
        ("forged_value", "SCENARIO_ORIGINAL_FACT_MISMATCH"),
        ("foreign_issuer", "SCENARIO_ORIGINAL_SOURCE_INVALID"),
        ("amendment", "SCENARIO_ORIGINAL_SOURCE_INVALID"),
        ("future_label", "SCENARIO_ORIGINAL_SOURCE_INVALID"),
        ("wrong_accession", "SCENARIO_ORIGINAL_SOURCE_INVALID"),
        ("wrong_unit", "SCENARIO_ORIGINAL_FACT_MISMATCH"),
        ("duplicate", "SCENARIO_FACT_ID_DUPLICATE"),
        ("missing", "SCENARIO_FACT_MISSING"),
        ("wrong_period_reference", "SCENARIO_ROLE_OR_PERIOD_INVALID"),
    ),
)
def test_source_or_selection_failures_remain_in_every_model_scenario(kind, code):
    req = request()
    target = next(fact for fact in req.facts if fact.normalized_field == "revenue")
    updates = {
        "forged_value": {"value": Decimal(12345)},
        "foreign_issuer": {"issuer_id": "OTHER"},
        "amendment": {"is_amendment": True},
        "future_label": {
            "available_at": req.source.valuation_timestamp.replace(year=2027)
        },
        "wrong_accession": {"accession_number": "0000000001-27-000001"},
        "wrong_unit": {"unit": "xbrli:shares"},
    }
    if kind == "duplicate":
        req = req.model_copy(update={"facts": (*req.facts, target)})
    elif kind == "missing":
        req = req.model_copy(
            update={"facts": tuple(fact for fact in req.facts if fact != target)}
        )
    elif kind == "wrong_period_reference":
        periods = list(req.periods)
        periods[1] = periods[1].model_copy(
            update={"fact_ids": {**periods[1].fact_ids, "revenue": target.fact_id}}
        )
        req = req.model_copy(update={"periods": tuple(periods)})
    else:
        req = req.model_copy(
            update={
                "facts": tuple(
                    fact.model_copy(update=updates[kind]) if fact == target else fact
                    for fact in req.facts
                )
            }
        )
    result = replay_operating_scenarios(req)
    assert len(result.results) == 2
    assert all(
        item.status == "abstained" and code in item.issue_codes
        for item in result.results
    )
    assert not any(item.nodes for item in result.results)
    assert len(result.retained_fact_ids) == len(req.facts)


def test_protocol_policy_mapping_and_nonnegative_assumptions_fail_closed():
    req = request()
    for updates in (
        {"policy_digest": "a" * 64},
        {"unresolved_classes": ()},
        {"mapping_manifest_digest": "b" * 64},
        {"periods": tuple(reversed(req.periods))},
        {"scenarios": (req.scenarios[0], req.scenarios[0])},
    ):
        with pytest.raises(ValidationError):
            OperatingScenarioRequestV1.model_validate({**req.model_dump(), **updates})
    with pytest.raises(ValidationError):
        OperatingScenarioV1.model_validate(
            {
                **req.scenarios[0].model_dump(),
                "operating_asset_fraction": Decimal("1.1"),
            }
        )


def test_impossible_gross_partition_retains_all_attempts_without_partial_nodes():
    req = request(parent_assets="40", cash="50")
    result = replay_operating_scenarios(req)
    assert result.results[0].status == "abstained"
    assert "SCENARIO_PARENT_INFEASIBLE" in result.results[0].issue_codes
    assert not any(item.nodes for item in result.results)


def test_conflicting_original_observations_cannot_be_hidden_by_picking_an_id():
    req = request(second_revenue="1234")
    result = replay_operating_scenarios(req)
    assert all(item.status == "abstained" for item in result.results)
    assert all("HISTORY_FACT_CONFLICT" in item.issue_codes for item in result.results)
    assert len(result.retained_fact_ids) == len(req.facts)


def test_deterministic_context_order_pins_and_atomic_repeat(tmp_path):
    req = request()
    expected = replay_operating_scenarios(req)
    with localcontext(Context(prec=7, rounding=ROUND_DOWN, Emin=-2, Emax=2)):
        assert canonical_bytes(replay_operating_scenarios(req)) == canonical_bytes(
            expected
        )
    assert (
        replay_operating_scenarios(
            req.model_copy(update={"facts": tuple(reversed(req.facts))})
        )
        == expected
    )
    changed = replay_operating_scenarios(
        req.model_copy(update={"protocol_version": "different-grid-v2"})
    )
    assert (
        changed.input_digest != expected.input_digest
        and changed.output_digest != expected.output_digest
    )
    store = ArtifactStore(tmp_path)
    first = publish_scenario_replay(
        req, artifacts=store, execution={"exact_commit": "a" * 40}
    )

    def inventory():
        return {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in tmp_path.iterdir()
            if path.is_file()
        }

    before = inventory()
    second = publish_scenario_replay(
        req, artifacts=ArtifactStore(tmp_path), execution={"exact_commit": "a" * 40}
    )
    assert first["wrote"] and not second["wrote"]
    assert (
        first["input_digest"] == second["input_digest"]
        and first["output_digest"] == second["output_digest"]
    )
    assert inventory() == before
    assert expected.output_digest == sha256_digest(
        expected.model_dump(exclude={"output_digest"})
    )
