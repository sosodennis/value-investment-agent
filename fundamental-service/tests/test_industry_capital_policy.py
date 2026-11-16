from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from fundamental_service.damodaran_source import DamodaranReferenceProvider
from fundamental_service.industry_capital import (
    adopt_industry_capital,
    industry_capital_evidence,
)
from fundamental_service.market_reference_selection import (
    IssuerMarketReferencePlanV1,
    MarketReferenceSelectionError,
    MarketReferenceSelectionPolicyV1,
    select_issuer_market_references,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import SourceUsePolicyV1
from fundamental_service.source_evidence import RetainedSourceV1
from test_industry_capital_source import (
    AlternateCapitalProvider,
    CAPTURE,
    METRICS,
    TERMS,
    VALUATION,
    admission,
    original,
)
from test_source_admission import _reference_policy, _terms


def capital_plan(at=VALUATION, issuer="CIK0000000001"):
    return IssuerMarketReferencePlanV1(
        issuer_id=issuer,
        policy_id="fcff_dcf-us-gaap-public-v3",
        valuation_at=at,
        industry_capital_policy="usd-industry-capital-proxy-v1",
        selections=tuple(
            MarketReferenceSelectionPolicyV1(
                policy_version="synthetic-exact-industry-v1",
                metric=metric,
                population="us-companies",
                subject_kind="industry",
                subject="Retail (Special Lines)",
                maximum_age_days=730,
            )
            for metric in METRICS
        ),
    )


def capital_inputs(at):
    source = replace(original(), captured_at=at - timedelta(days=1))
    rules = tuple(
        _reference_policy()
        .rules[0]
        .model_copy(
            update={
                "rule_id": "synthetic-capital-" + metric,
                "metric_id": metric,
                "population": "us-companies",
                "source_version": source.source_version,
            }
        )
        for metric in METRICS
    )
    policy = SourceUsePolicyV1(
        policy_version="synthetic-capital-use-v1",
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
    )
    return tuple(
        dict(
            metric=metric,
            sources=(source,),
            terms=(_terms(),),
            valuation_at=at,
            policy=policy,
        )
        for metric in METRICS
    )


def selection(*, alternate=False, weights=("0.225", "0.775")):
    provider = AlternateCapitalProvider() if alternate else DamodaranReferenceProvider()
    if alternate:
        source = RetainedSourceV1(
            source_id="synthetic-json-reference",
            uri="https://example.test/capital.json",
            source_version="synthetic-json-v1",
            terms_reference=TERMS.uri,
            captured_at=CAPTURE,
            content=canonical_bytes(
                {
                    "industry.equity_beta": "1.23",
                    "industry.pre_tax_cost_of_debt": "0.0578",
                    "industry.debt_weight": weights[0],
                    "industry.equity_weight": weights[1],
                }
            ),
        )
    else:
        source = original()
    admissions = tuple(admission(provider, source, metric) for metric in METRICS)
    return select_issuer_market_references(capital_plan(), admissions=admissions)


@pytest.mark.parametrize("alternate", (False, True))
def test_policy_adopts_interchangeable_industry_inputs_without_company_relabeling(
    alternate,
):
    bundle = selection(alternate=alternate)
    result = adopt_industry_capital(bundle)
    assert result.values["beta"] == (
        Decimal("1.23") if alternate else Decimal.from_float(1.23)
    )
    assert result.values["debt_weight"] + result.values["equity_weight"] == 1
    assert result.values["pre_tax_cost_of_debt"] == (
        Decimal("0.0578") if alternate else Decimal.from_float(0.0578)
    )
    evidence = industry_capital_evidence(result)
    assert {item.method for item in evidence} == {"approved_policy"}
    assert all(item.content_hash == result.output_digest for item in evidence)
    assert all("not observed issuer" in item.rationale for item in evidence)
    assert all(
        sha256_digest(bundle.plan) in trace.source_refs
        for trace in result.traces.values()
    )
    with localcontext() as context:
        context.prec = 3
        repeat = adopt_industry_capital(bundle)
    assert canonical_bytes(result) == canonical_bytes(repeat)


@pytest.mark.parametrize(
    "weights", [("0", "1"), ("1", "0"), ("0.2", "0.80000000000001")]
)
def test_weight_rule_accepts_endpoints_and_only_normalizes_representation_tolerance(
    weights,
):
    result = adopt_industry_capital(selection(alternate=True, weights=weights))
    assert result.values["debt_weight"] + result.values["equity_weight"] == 1
    assert 0 <= result.values["debt_weight"] <= 1


@pytest.mark.parametrize(
    "weights", [("0", "0"), ("0.2", "0.7"), ("0.2", "0.80000000001")]
)
def test_inconsistent_published_weights_refuse_without_silent_filling(weights):
    with pytest.raises(MarketReferenceSelectionError) as caught:
        adopt_industry_capital(selection(alternate=True, weights=weights))
    assert caught.value.code == "INDUSTRY_CAPITAL_WEIGHTS_INCONSISTENT"


@pytest.mark.parametrize(
    "change,code",
    [
        ("rule", "INDUSTRY_CAPITAL_POLICY_MISSING"),
        ("missing", "INDUSTRY_CAPITAL_SELECTION_REFUSED"),
        ("subject", "INDUSTRY_CAPITAL_BASIS_MISMATCH"),
        ("source", "INDUSTRY_CAPITAL_BASIS_MISMATCH"),
    ],
)
def test_incomplete_or_cross_basis_selections_cannot_form_an_industry_proxy(
    change, code
):
    bundle = selection()
    if change == "rule":
        bundle = bundle.model_copy(
            update={
                "plan": bundle.plan.model_copy(update={"industry_capital_policy": None})
            }
        )
    elif change == "missing":
        bundle = bundle.model_copy(update={"selections": bundle.selections[:-1]})
    else:
        item = bundle.selections[0]
        if change == "subject":
            item = item.model_copy(
                update={
                    "policy": item.policy.model_copy(
                        update={"subject": "Other industry"}
                    )
                }
            )
        else:
            item = item.model_copy(
                update={
                    "trace": item.trace.model_copy(update={"source_refs": ("a" * 64,)})
                }
            )
        bundle = bundle.model_copy(
            update={"selections": (item, *bundle.selections[1:])}
        )
    with pytest.raises(MarketReferenceSelectionError) as caught:
        adopt_industry_capital(bundle)
    assert caught.value.code == code


def test_old_reference_plans_keep_their_canonical_bytes_when_no_rule_is_adopted():
    payload = capital_plan().model_dump(exclude={"industry_capital_policy"})
    plan = IssuerMarketReferencePlanV1.model_validate(payload)
    assert plan.industry_capital_policy is None
    assert canonical_bytes(plan) == canonical_bytes(payload)
