from datetime import datetime

from fundamental_service.automatic_market_policy import (
    AutomaticMarketPolicyPolicyV1,
    evaluate_automatic_market_policy,
)
from fundamental_service.issuer_market_policy_plan import (
    IssuerMarketReferencePlanPolicyV1,
    build_issuer_market_reference_plan,
)
from fundamental_service.market_source_selection import USD_RISK_FREE_POLICY
from fundamental_service.terminal_growth import TerminalGrowthPlanV1
from test_issuer_market_policy_plan import _classification, _mapped
from fundamental_service.serialization import canonical_bytes, sha256_digest


def _plan_decision():
    classification = _classification()
    country, industry = _mapped(classification)
    return build_issuer_market_reference_plan(
        classification,
        country_mapping=country,
        industry_mapping=industry,
        policy=IssuerMarketReferencePlanPolicyV1(),
        policy_id="fcff_dcf-us-gaap-public-v3",
    )


def _market_policy(at: datetime) -> AutomaticMarketPolicyPolicyV1:
    return AutomaticMarketPolicyPolicyV1(
        policy_version="automatic-market-policy-test-v1",
        currency="USD",
        risk_free_policy=USD_RISK_FREE_POLICY,
        terminal_growth_plan=TerminalGrowthPlanV1(
            issuer_id="0000320193",
            policy_id="fcff_dcf-us-gaap-public-v3",
            valuation_at=at,
            gdp_horizon_years=10,
            maximum_gdp_period_age_days=500,
            risk_free_policy=USD_RISK_FREE_POLICY,
        ),
    )


def test_missing_admissions_are_retained_as_a_stable_refusal():
    at = _plan_decision().valuation_at
    result = evaluate_automatic_market_policy(
        _plan_decision(), policy=_market_policy(at), admissions=()
    )

    assert result.status == "refused"
    assert result.inputs is None
    assert "MARKET_REFERENCE_SOURCE_UNAVAILABLE" in result.issue_codes
    assert "ISSUER_MARKET_REFERENCE_SELECTION_REFUSED" in result.issue_codes


def test_plan_refusal_never_becomes_a_market_policy():
    decision = _plan_decision()
    refused = decision.model_copy(
        update={"status": "refused", "issue_codes": ("MAPPING_MISSING",), "plan": None}
    )
    payload = refused.model_dump(exclude={"output_digest"})
    refused = refused.model_copy(update={"output_digest": sha256_digest(payload)})
    result = evaluate_automatic_market_policy(
        refused,
        policy=_market_policy(decision.valuation_at),
        admissions=(),
    )

    assert result.status == "refused"
    assert result.inputs is None
    assert "MAPPING_MISSING" in result.issue_codes


def test_repeated_refusal_is_byte_identical():
    decision = _plan_decision()
    policy = _market_policy(decision.valuation_at)
    first = evaluate_automatic_market_policy(decision, policy=policy, admissions=())
    repeated = evaluate_automatic_market_policy(
        decision, policy=policy, admissions=(), expected=first
    )
    assert canonical_bytes(repeated) == canonical_bytes(first)
