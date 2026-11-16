"""An explicitly unknown baseline is never a zero, observation or FCFF operand."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.operating_label_contracts import ConditionalLabelRequestV1
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenario_contracts import (
    BASELINE_SCENARIO_POLICY,
    BASELINE_SOURCE_POLICY,
    OperatingScenarioRequestV1,
    scenario_policy_digest,
)
from fundamental_service.operating_scenario_policy import UnconsumedBaselineCapexV1
from fundamental_service.operating_scenarios import (
    build_scenario_history,
    replay_operating_scenarios,
    resolve_scenario_observations,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.valuation_preparation import (
    PreparationError,
    derive_historical_metrics,
)
from test_operating_labels import comparison_request


def split_baseline():
    req = unknown_baseline(comparison_request().decision)
    original = req.source.originals[0]
    stock_roles = {"current_assets", "current_liabilities", "cash_and_equivalents"}
    source = original.source.model_copy(
        update={
            "content_hash": "b" * 64,
            "parser_input_hash": "b" * 64,
            "accession_number": "0000000001-26-000003",
            "uri": "https://www.sec.gov/Archives/edgar/data/1/000000000126000003/stocks.xml",
            "available_at": original.source.available_at - timedelta(days=1),
        }
    )
    report = original.report.model_copy(update={"source_content_hash": "b" * 64})
    stock_original = evaluate_original_issuer(
        report, source=source, decision_at=original.decision_at
    )
    assert stock_original.status == "matched"
    stocks = tuple(
        c.canonical_fact(quality=req.facts[0].quality)
        for m in req.mappings
        if m.normalized_field in stock_roles
        for c in parsed_facts_to_candidates(
            report,
            source=source,
            issuer_id=source.cik,
            normalized_field=m.normalized_field,
            mapping=m,
        )
        if (c.instant or c.period_end).year == 2023
    )
    retained = tuple(
        f
        for f in req.facts
        if not (f.normalized_field in stock_roles and f.period_end.year == 2023)
    )
    first = req.periods[0]
    period = first.model_copy(
        update={
            "fact_ids": {
                **{k: v for k, v in first.fact_ids.items() if k not in stock_roles},
                **{f.normalized_field: f.fact_id for f in stocks},
            },
            "unconsumed_capex": first.unconsumed_capex.model_copy(
                update={"source_content_hash": "b" * 64}
            ),
        }
    )
    request = req.model_copy(
        update={
            "source": compose_issuer_operating_source(
                (original, stock_original),
                valuation_timestamp=req.source.valuation_timestamp,
            ),
            "facts": (*retained, *stocks),
            "periods": (period, *req.periods[1:]),
        }
    )
    return OperatingScenarioRequestV1.model_validate_json(canonical_bytes(request))


def test_versioned_baseline_families_retain_both_originals_with_unchanged_arithmetic():
    req = split_baseline()
    selected = resolve_scenario_observations(req, req.periods)[0]
    assert {f.source.content_hash for f in selected.values()} == {
        "b" * 64,
        next(
            o.source.content_hash
            for o in req.source.originals
            if o.source.content_hash != "b" * 64
        ),
    }
    result = replay_operating_scenarios(req)
    assert result.results[0].status == "provisional_scenario"
    assert (
        result.results[0].forecast
        == replay_operating_scenarios(comparison_request().decision).results[0].forecast
    )


def test_baseline_family_cannot_hide_an_incomplete_stock_source():
    req = split_baseline()
    fact_id = req.periods[0].fact_ids["current_liabilities"]
    # Keep the explicit selected ID but remove its candidate: no source fallback.
    result = replay_operating_scenarios(
        req.model_copy(
            update={"facts": tuple(f for f in req.facts if f.fact_id != fact_id)}
        )
    )
    assert all(
        r.status == "abstained" and "SCENARIO_FACT_MISSING" in r.issue_codes
        for r in result.results
    )


def test_newer_complete_family_wins_and_cannot_be_ignored():
    req = split_baseline()
    original = next(
        o for o in req.source.originals if o.source.content_hash != "b" * 64
    )
    stocks = tuple(
        c.canonical_fact(quality=req.facts[0].quality)
        for m in req.mappings
        if m.normalized_field
        in {"current_assets", "current_liabilities", "cash_and_equivalents"}
        for c in parsed_facts_to_candidates(
            original.report,
            source=original.source,
            issuer_id=original.source.cik,
            normalized_field=m.normalized_field,
            mapping=m,
        )
        if (c.instant or c.period_end).year == 2023
    )
    result = replay_operating_scenarios(
        req.model_copy(update={"facts": (*req.facts, *stocks)})
    )
    assert all(
        r.status == "abstained"
        and "SCENARIO_SELECTION_POLICY_MISMATCH" in r.issue_codes
        for r in result.results
    )


def unknown_baseline(req):
    first = req.periods[0]
    fact = next(
        f for f in req.facts if f.fact_id == first.fact_ids["capital_expenditure"]
    )
    marker = UnconsumedBaselineCapexV1(
        source_content_hash=fact.source.content_hash,
        evidence_digests=("a" * 64,),
        rationale="The continuing PPE cash amount is unresolved; the first-period value is not consumed.",
    )
    period = first.model_copy(
        update={
            "fact_ids": {
                r: i for r, i in first.fact_ids.items() if r != "capital_expenditure"
            },
            "unconsumed_capex": marker,
        }
    )
    scenarios = tuple(
        s.model_copy(
            update={
                "continuing_capex_fractions": {
                    y: v
                    for y, v in s.continuing_capex_fractions.items()
                    if y != first.fiscal_year
                }
            }
        )
        for s in req.scenarios
    )
    changed = req.model_copy(
        update={
            "contract_version": "fundamental.operating-scenarios.v2",
            "policy_version": BASELINE_SCENARIO_POLICY,
            "source_selection_policy": BASELINE_SOURCE_POLICY,
            "policy_digest": scenario_policy_digest(BASELINE_SCENARIO_POLICY),
            "periods": (period, *req.periods[1:]),
            "scenarios": scenarios,
            "facts": tuple(f for f in req.facts if f != fact),
        }
    )
    return OperatingScenarioRequestV1.model_validate_json(canonical_bytes(changed))


def test_v1_wire_and_all_digests_remain_exact():
    req = comparison_request()
    assert (
        sha256_digest(req)
        == "7e527b02e99d980cf95a42fe1618017d56257b3071a77a992d59efe580fedb37"
    )
    assert (
        sha256_digest(req.decision)
        == "99388392cf5966b386c4f547246d720716e49735d077524cf2b1b10b2d7b77ca"
    )
    assert (
        sha256_digest(replay_operating_scenarios(req.decision))
        == "f1aed1c7be88b0d9dff661beab1799f5e1fe98bae7239434c1647ef867ec48e5"
    )
    assert (
        sha256_digest(replay_operating_comparison(req))
        == "bc7e1cf3e7e33275b6f4992ce950fec4321bcde29453a0509657d435d68ebf60"
    )
    assert (
        scenario_policy_digest()
        == "2744649f593e8813665bfbf8efcf1170cc6ad514940280a4889fb20e2c46ebff"
    )
    assert "unconsumed_capex" not in req.decision.periods[0].model_dump()


def test_baseline_unknown_preserves_formal_forecast_and_conditional_labels():
    req = comparison_request()
    old = replay_operating_scenarios(req.decision)
    decision = unknown_baseline(req.decision)
    before = canonical_bytes(decision)
    result = replay_operating_scenarios(decision)
    assert canonical_bytes(decision) == before
    assert canonical_bytes(result) == canonical_bytes(
        replay_operating_scenarios(decision)
    )
    assert result.contract_version == "fundamental.operating-scenario-replay.v3"
    fcff, transition = result.results
    assert fcff.forecast == old.results[0].forecast
    assert [(n.node_id, n.value) for n in fcff.nodes] == [
        (n.node_id, n.value) for n in old.results[0].nodes
    ]
    assert fcff.period_inputs[0].capex == decision.periods[0].unconsumed_capex
    assert "BASELINE_CAPEX_UNKNOWN_UNCONSUMED" in fcff.issue_codes
    assert "TRANSITION_EVIDENCE_MISSING" in transition.issue_codes
    assert transition.status == "abstained"
    assert all(
        m.fiscal_year != 2023 or m.metric_id != "realized_fcff"
        for m in fcff.historical_metrics.metrics
    )
    assert result.supported_history_threshold is None
    assert not any(
        f.normalized_field == "capital_expenditure" and f.period_end.year == 2023
        for f in decision.facts
    )
    changed = req.model_copy(
        update={
            "contract_version": "fundamental.operating-comparison.v2",
            "decision": decision,
            "decision_input_digest": sha256_digest(decision),
        }
    )
    outcome = replay_operating_comparison(changed)
    baseline = replay_operating_comparison(req)
    assert outcome.labels == baseline.labels
    assert [r.model_dump(exclude={"issue_codes"}) for r in outcome.comparisons] == [
        r.model_dump(exclude={"issue_codes"}) for r in baseline.comparisons
    ]
    assert outcome.label_policy_digest == baseline.label_policy_digest
    assert outcome.label_input_digest == baseline.label_input_digest
    assert outcome.contract_version == "fundamental.operating-comparison-replay.v2"


@pytest.mark.parametrize("baseline_capex", ("0", "20", "999999999"))
def test_observed_baseline_capex_perturbation_cannot_change_metrics(baseline_capex):
    req = comparison_request().decision
    prepared = build_scenario_history(
        req.periods,
        resolve_scenario_observations(req, req.periods),
        req.scenarios[0],
        policy_digest=req.policy_digest,
        scope_evidence=req.scope_assumption_evidence_digests,
    )
    before = derive_historical_metrics(
        prepared.history, estimated_inputs=prepared.estimates
    )
    changed = (
        replace(prepared.estimates[0], capital_expenditure=Decimal(baseline_capex)),
        *prepared.estimates[1:],
    )
    assert (
        derive_historical_metrics(prepared.history, estimated_inputs=changed) == before
    )


@pytest.mark.parametrize(
    "fault", ("v1", "digest", "later", "allocation", "missing_later", "missing_scalar")
)
def test_exemption_cannot_remove_a_consumed_role_or_enter_v1(fault):
    req = unknown_baseline(comparison_request().decision)
    raw = req.model_dump(mode="json")
    if fault == "v1":
        raw["contract_version"] = "fundamental.operating-scenarios.v1"
    elif fault == "digest":
        raw["policy_digest"] = scenario_policy_digest()
    elif fault == "later":
        raw["periods"][1]["unconsumed_capex"] = raw["periods"][0]["unconsumed_capex"]
        del raw["periods"][1]["fact_ids"]["capital_expenditure"]
    elif fault == "allocation":
        raw["scenarios"][0]["continuing_capex_fractions"]["2023"] = "0"
    elif fault == "missing_later":
        del raw["periods"][1]["fact_ids"]["capital_expenditure"]
    else:
        del raw["periods"][0]["fact_ids"]["revenue"]
    with pytest.raises(ValidationError):
        OperatingScenarioRequestV1.model_validate_json(canonical_bytes(raw))


def test_labels_reject_unknown_baseline_and_source_mismatch_is_retained():
    req = comparison_request()
    raw = req.label.model_dump(mode="json")
    marker = unknown_baseline(req.decision).periods[0].unconsumed_capex
    raw["periods"][0]["unconsumed_capex"] = marker.model_dump(mode="json")
    del raw["periods"][0]["fact_ids"]["capital_expenditure"]
    with pytest.raises(ValidationError, match="decision-only"):
        ConditionalLabelRequestV1.model_validate_json(canonical_bytes(raw))
    decision = unknown_baseline(req.decision)
    first = decision.periods[0]
    changed = decision.model_copy(
        update={
            "periods": (
                first.model_copy(
                    update={
                        "unconsumed_capex": marker.model_copy(
                            update={"source_content_hash": "0" * 64}
                        )
                    }
                ),
                *decision.periods[1:],
            )
        }
    )
    replay = replay_operating_scenarios(changed)
    assert all(
        r.status == "abstained" and "SCENARIO_BASELINE_SOURCE_MISMATCH" in r.issue_codes
        for r in replay.results
    )


@pytest.mark.parametrize("fault", ("profile", "digest", "later", "invented_fact"))
def test_shared_metrics_fail_closed_on_nonoperand_outside_pinned_baseline(fault):
    req = unknown_baseline(comparison_request().decision)
    prepared = build_scenario_history(
        req.periods,
        resolve_scenario_observations(req, req.periods),
        req.scenarios[0],
        policy_digest=req.policy_digest,
        policy_version=req.policy_version,
        scope_evidence=req.scope_assumption_evidence_digests,
    )
    history, estimates = prepared.history, prepared.estimates
    if fault == "profile":
        history = replace(history, requirements_profile_id="exact-full")
    elif fault == "digest":
        history = replace(history, requirements_profile_digest="0" * 64)
    elif fault == "later":
        estimates = (
            replace(estimates[0], capital_expenditure=Decimal(20)),
            replace(estimates[1], capital_expenditure=estimates[0].capital_expenditure),
            *estimates[2:],
        )
    else:
        estimates = (replace(estimates[0], capex_facts=(req.facts[0],)), *estimates[1:])
    with pytest.raises(PreparationError, match="research baseline"):
        derive_historical_metrics(history, estimated_inputs=estimates)
