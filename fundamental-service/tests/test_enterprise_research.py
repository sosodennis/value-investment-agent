"""Enterprise conclusions share formal DCF math without inventing equity claims."""

from datetime import timedelta
from decimal import Context, Decimal, Inexact, ROUND_DOWN, Rounded, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.calculator import calculate
from fundamental_service.contracts import (
    ForecastAssumptionsV1,
    UncertaintyV1,
    WaccAssumptionsV1,
)
from fundamental_service.enterprise_projection import project_enterprise_nodes
from fundamental_service.enterprise_research import (
    EnterpriseDiscountScenarioV1,
    EnterpriseResearchRequestV1,
    research_enterprise_value,
)
from fundamental_service.operating_projection import OperatingProjectionError
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_operating_forecast import operating_facts, snapshot
from test_valuation_preparation import (
    RELEASE_DIGEST,
    VALUATION_TIME,
    _fact,
    _facts,
    _market_policy,
    _prepare,
)


def scenario(name="baseline", **changes):
    policy = _market_policy()
    policy = policy.model_copy(
        update={
            "evidence": {
                field: trace.model_copy(
                    update={"as_of": VALUATION_TIME, "available_at": VALUATION_TIME}
                )
                for field, trace in policy.evidence.items()
            },
            **changes,
        }
    )
    return EnterpriseDiscountScenarioV1(
        scenario_id=name,
        market_policy=policy,
        rationale="Explicit synthetic discount scenario; no market-policy authority is asserted.",
        evidence_digests=("e" * 64,),
    )


def request(**changes):
    facts = changes.pop("facts", operating_facts())
    facts = tuple(
        fact.model_copy(
            update={"captured_at": max(fact.captured_at, fact.available_at)}
        )
        for fact in facts
    )
    return EnterpriseResearchRequestV1(
        **{
            "facts": facts,
            "snapshot": snapshot(),
            "model_id": "fcff_dcf",
            "model_version": "fcff_dcf-v2",
            "policy_id": "fcff_dcf-us-gaap-public-v3",
            "policy_version": "fcff_dcf-v2-quality-v2",
            "mapping_version": "sec-canonical-mapping-v1",
            "data_release_manifest_digest": RELEASE_DIGEST,
            "scenarios": (scenario(),),
            **changes,
        }
    )


@pytest.mark.parametrize("model", ("fcff_dcf", "transition_fcff_dcf"))
def test_shared_enterprise_stage_matches_full_calculator_nodes(model):
    filing = _fact("filed_operating_evidence", 2025, "1").model_copy(
        update={"value": "filed evidence"}
    )
    extra = (filing,) if model == "transition_fcff_dcf" else ()
    prepared = _prepare(
        (*_facts(), *extra), market_policy=_market_policy(), model_id=model
    )
    assert prepared.input is not None
    full_input = prepared.input.model_copy(
        update={"uncertainty": UncertaintyV1(mode="none")}
    ).with_digest()
    full = calculate(full_input, allow_provisional=True)
    assumptions = full_input.assumptions
    shared = project_enterprise_nodes(
        assumptions.forecast,
        wacc=assumptions.wacc,
        terminal_growth=assumptions.terminal_growth,
        historical_fact_ids=tuple(full_input.historical_facts),
    )
    assert full.nodes[:-2] == shared
    research = research_enterprise_value(
        request(
            facts=(*operating_facts(), *extra),
            model_id=model,
            model_version=f"{model}-v2",
        )
    )
    result = research.results[0]
    assert result.status == "provisional_conditional_enterprise_value"
    assert result.enterprise_value == shared[-1].value
    assert research.operating_forecast.forecast == assumptions.forecast
    assert research.operating_forecast.tax_rate == assumptions.wacc.tax_rate
    assert not {"equity_value", "per_share_value"} & {n.node_id for n in result.nodes}
    assert research.supported_history_threshold is None
    assert "capital_claim_completeness" in research.unestablished_claims
    assert _prepare(operating_facts(), market_policy=_market_policy()).input is None


def test_constant_perpetual_cash_flow_has_hand_checkable_enterprise_value():
    nodes = project_enterprise_nodes(
        ForecastAssumptionsV1(
            base_revenue=Decimal("100"),
            revenue_growth=(Decimal("0"),),
            operating_margin=(Decimal("0.2"),),
            reinvestment_rate=(Decimal("0.5"),),
        ),
        wacc=WaccAssumptionsV1(
            risk_free_rate=Decimal("0.1"),
            beta=Decimal("0"),
            equity_risk_premium=Decimal("0"),
            pre_tax_cost_of_debt=Decimal("0"),
            tax_rate=Decimal("0.25"),
            debt_weight=Decimal("0"),
            equity_weight=Decimal("1"),
        ),
        terminal_growth=Decimal("0"),
        historical_fact_ids=("reported-revenue",),
    )
    assert next(n.value for n in nodes if n.node_id == "fcff_1") == Decimal("7.5")
    assert nodes[-1].value == Decimal("75")


@pytest.mark.parametrize("trapping", (False, True))
def test_canonical_inputs_and_hostile_decimal_context_reuse_artifacts(
    tmp_path, trapping
):
    first = request(scenarios=(scenario("z"), scenario("a")))
    expected = research_enterprise_value(first)
    reordered = request(
        facts=tuple(reversed(first.facts)), scenarios=tuple(reversed(first.scenarios))
    )
    context = Context(prec=7, rounding=ROUND_DOWN, Emin=-2, Emax=2, clamp=1)
    context.traps[Inexact] = trapping
    context.traps[Rounded] = trapping
    with localcontext(context) as caller:
        before = str(caller)
        repeated = research_enterprise_value(reordered)
        assert str(caller) == before
    assert canonical_bytes(repeated) == canonical_bytes(expected)
    store = ArtifactStore(tmp_path)
    initial = store.put_with_receipt(expected.output_digest, expected)
    path_inventory = {
        str(p): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    again = store.put_with_receipt(repeated.output_digest, repeated)
    assert initial.wrote and not again.wrote
    assert {
        str(p): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    } == path_inventory


@pytest.mark.parametrize("change", ("missing", "future", "foreign"))
def test_incomplete_operating_evidence_retains_every_scenario(change):
    facts = operating_facts()
    if change == "missing":
        facts = tuple(f for f in facts if f.normalized_field != "revenue")
    else:
        facts = tuple(
            f.model_copy(
                update={"available_at": VALUATION_TIME + timedelta(days=1)}
                if change == "future"
                else {"issuer_id": "foreign-issuer"}
            )
            if f.normalized_field == "revenue"
            else f
            for f in facts
        )
    result = research_enterprise_value(
        request(facts=facts, scenarios=(scenario("a"), scenario("b")))
    )
    assert result.operating_forecast.status == "abstained"
    assert len(result.results) == 2
    assert all(
        r.status == "abstained"
        and not r.nodes
        and r.enterprise_value is None
        and "ENTERPRISE_OPERATING_INPUTS_UNAVAILABLE" in r.issue_codes
        for r in result.results
    )
    assert result.input_digest == sha256_digest(
        request(facts=facts, scenarios=(scenario("a"), scenario("b")))
    )


@pytest.mark.parametrize(
    "kind",
    ("undated", "unavailable", "future", "future_availability", "growth", "discount"),
)
def test_invalid_discount_case_is_retained_beside_successful_sibling(kind):
    bad = scenario("invalid")
    policy = bad.market_policy
    if kind in {"undated", "unavailable", "future", "future_availability"}:
        when = (
            None
            if kind in {"undated", "unavailable"}
            else VALUATION_TIME + timedelta(days=1)
        )
        update = (
            {"available_at": when}
            if kind in {"unavailable", "future_availability"}
            else {"as_of": when, "available_at": when}
        )
        traces = {k: v.model_copy(update=update) for k, v in policy.evidence.items()}
        policy = policy.model_copy(update={"evidence": traces})
    else:
        policy = policy.model_copy(
            update={"terminal_growth": Decimal("0.5")}
            if kind == "growth"
            else {"risk_free_rate": Decimal("-1")}
        )
    bad = bad.model_copy(update={"market_policy": policy})
    result = research_enterprise_value(request(scenarios=(scenario(), bad)))
    assert result.results[0].status == "provisional_conditional_enterprise_value"
    refused = result.results[1]
    assert refused.status == "abstained" and not refused.nodes
    assert refused.enterprise_value is None and refused.scenario == bad
    assert any(
        "DISCOUNT" in code or "SCENARIO_EVIDENCE" in code
        for code in refused.issue_codes
    )


def test_versions_and_assumption_evidence_bind_identity_without_granting_authority():
    base = request()
    expected = research_enterprise_value(base)
    changed = research_enterprise_value(
        request(mapping_version="different-mapping-evidence")
    )
    assert expected.input_digest != changed.input_digest
    assert expected.output_digest != changed.output_digest
    assert expected.results == changed.results
    altered = base.scenarios[0].model_copy(update={"evidence_digests": ("a" * 64,)})
    assert (
        research_enterprise_value(request(scenarios=(altered,))).input_digest
        != expected.input_digest
    )
    with pytest.raises(OperatingProjectionError, match="requires executable version"):
        research_enterprise_value(request(model_version="unbound-version"))
    with pytest.raises(ValidationError, match="unique"):
        request(scenarios=(scenario(), scenario()))
    with pytest.raises(ValidationError):
        EnterpriseDiscountScenarioV1(
            **{**scenario().model_dump(), "evidence_digests": ("unbound",)}
        )
