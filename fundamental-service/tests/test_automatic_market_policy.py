import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, Inexact, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.automatic_market_policy import (
    AutomaticMarketPolicyPolicyV1,
    evaluate_automatic_market_policy,
)
from fundamental_service.classification_crosswalk import (
    ClassificationCrosswalkPolicyV1,
    apply_industry_crosswalk,
)
from fundamental_service.issuer_classification import reproduce_issuer_classification
from fundamental_service.issuer_country_crosswalk import (
    CountryCrosswalkPolicyV1,
    apply_country_crosswalk,
)
from fundamental_service.issuer_market_policy_plan import (
    IssuerMarketReferencePlanPolicyV1,
    build_issuer_market_reference_plan,
)
from fundamental_service.market_reference import (
    MarketReferenceVintageV1,
    ReferenceMetric,
    ReferenceRowV1,
)
from fundamental_service.market_source_selection import USD_RISK_FREE_POLICY
from fundamental_service.sec_classification_source import (
    SecSubmissionClassificationProvider,
)
from fundamental_service.sec_sic_damodaran_crosswalk import (
    DAMODARAN_US_INDUSTRY_TAXONOMY,
    SecSicDamodaranIndustryCrosswalk,
)
from fundamental_service.sec_state_country_crosswalk import (
    DAMODARAN_COUNTRY_TAXONOMY,
    SEC_STATE_COUNTRY_SCHEME,
    SecStateCountryCrosswalk,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
    admit_macro_source,
    admit_reference_source,
)
from fundamental_service.source_evidence import (
    RetainedSourceV1,
    SourceArtifactV1,
)
from fundamental_service.terminal_growth import TerminalGrowthPlanV1
from test_issuer_classification import request, sec_submission
from test_terminal_growth import AnnualAndDailyProvider, _inputs as macro_inputs

AT = datetime(2026, 11, 13, tzinfo=UTC)


class AlternateReferenceProvider:
    provider_id = "synthetic-alternate-market-reference"

    values = {
        "country.equity_risk_premium": ("countries", "United States", "0.045"),
        "industry.equity_beta": (
            "us-companies",
            "Computers/Peripherals",
            "1.18",
        ),
        "industry.pre_tax_cost_of_debt": (
            "us-companies",
            "Computers/Peripherals",
            "0.0578",
        ),
        "industry.debt_weight": (
            "us-companies",
            "Computers/Peripherals",
            "0.225",
        ),
        "industry.equity_weight": (
            "us-companies",
            "Computers/Peripherals",
            "0.775",
        ),
    }

    def supports(self, metric: ReferenceMetric) -> bool:
        return metric in self.values

    def reproduce_vintage(self, *, metric, sources):
        source = sources[0]
        population, subject, value = json.loads(source.content)[metric]
        digest = hashlib.sha256(source.content).hexdigest()
        kind = "country" if metric.startswith("country.") else "industry"
        return MarketReferenceVintageV1.build(
            metric=metric,
            population=population,
            unit="multiple" if metric == "industry.equity_beta" else "fraction",
            provider_id=self.provider_id,
            source_version=source.source_version,
            source_updated_on=source.captured_at.date(),
            available_at=source.captured_at,
            captured_at=source.captured_at,
            artifacts=(
                SourceArtifactV1(
                    source_id=source.source_id,
                    uri=source.uri,
                    source_version=source.source_version,
                    terms_reference=source.terms_reference,
                    content_sha256=digest,
                    captured_at=source.captured_at,
                ),
            ),
            rows=(
                ReferenceRowV1(
                    subject=subject,
                    subject_kind=kind,
                    value=Decimal(value),
                    missing_reason=None,
                    raw_value=value,
                    numeric_encoding="decimal_text",
                    value_basis="published_cell",
                    number_format="0.00%" if kind == "country" else "0.00",
                    locator=f"$['{metric}']",
                    source_sha256=digest,
                ),
            ),
        )


def _plan_decision(at: datetime = AT):
    classification = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(valuation_at=at),
        sources=(sec_submission(),),
    )
    country_provider = SecStateCountryCrosswalk()
    country = apply_country_crosswalk(
        classification,
        policy=CountryCrosswalkPolicyV1(
            provider_id=country_provider.provider_id,
            mapping_version=country_provider.mapping_version,
            mapping_digest=country_provider.mapping_digest,
            source_scheme=SEC_STATE_COUNTRY_SCHEME,
            target_taxonomy=DAMODARAN_COUNTRY_TAXONOMY,
        ),
        provider=country_provider,
    )
    industry_provider = SecSicDamodaranIndustryCrosswalk()
    industry = apply_industry_crosswalk(
        classification,
        policy=ClassificationCrosswalkPolicyV1(
            provider_id=industry_provider.provider_id,
            mapping_version=industry_provider.mapping_version,
            mapping_digest=industry_provider.mapping_digest,
            source_scheme="sec-sic-v1",
            target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        ),
        provider=industry_provider,
    )
    return build_issuer_market_reference_plan(
        classification,
        country_mapping=country,
        industry_mapping=industry,
        policy=IssuerMarketReferencePlanPolicyV1(),
        policy_id="fcff_dcf-us-gaap-public-v3",
    )


def _reference_admissions(at: datetime):
    provider = AlternateReferenceProvider()
    source = RetainedSourceV1(
        source_id="synthetic-alternate-reference",
        uri="https://example.test/market-reference.json",
        source_version="synthetic-alternate-reference-v1",
        terms_reference="https://example.test/terms",
        content=canonical_bytes(provider.values),
        captured_at=at - timedelta(days=1),
    )
    terms = RetainedSourceV1(
        source_id="synthetic-reference-terms",
        uri="https://example.test/terms",
        source_version="synthetic-terms-v1",
        terms_reference="https://example.test/terms",
        content=b"Synthetic license terms for tests only",
        captured_at=source.captured_at,
    )
    rules = tuple(
        SourceUseRuleV1(
            rule_id=f"alternate-market:{metric}",
            provider_id=provider.provider_id,
            metric_id=metric,
            population=provider.values[metric][0],
            source_id=source.source_id,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            permitted_uses=("valuation_preparation",),
            terms=(
                TermsRequirementV1(
                    uri=terms.uri,
                    content_sha256=hashlib.sha256(terms.content).hexdigest(),
                ),
            ),
            required_notices=("Synthetic test source",),
            basis="Synthetic provider substitution test",
        )
        for metric in sorted(provider.values)
    )
    policy = SourceUsePolicyV1(
        policy_version="synthetic-alternate-market-v1",
        rules=rules,
    )
    return tuple(
        admit_reference_source(
            provider,
            metric=metric,
            sources=(source,),
            terms=(terms,),
            valuation_at=at,
            policy=policy,
        )
        for metric in sorted(provider.values)
    )


def _admissions(at: datetime):
    macros = tuple(
        admit_macro_source(AnnualAndDailyProvider(), **item)
        for item in macro_inputs(at=at)
    )
    return (*_reference_admissions(at), *macros)


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


def test_alternate_provider_assembles_complete_source_bound_market_policy():
    decision = _plan_decision()
    admissions = _admissions(AT)
    assert all(item.status == "admitted" for item in admissions)
    result = evaluate_automatic_market_policy(
        decision, policy=_market_policy(AT), admissions=admissions
    )

    assert result.status == "approved", result.issue_codes
    assert result.inputs is not None
    assert result.inputs.beta == Decimal("1.18")
    assert result.inputs.equity_risk_premium == Decimal("0.045")
    assert result.inputs.pre_tax_cost_of_debt == Decimal("0.0578")
    assert result.inputs.debt_weight == Decimal("0.225")
    assert result.inputs.equity_weight == Decimal("0.775")
    assert result.inputs.risk_free_rate == Decimal("0.0425")
    assert result.inputs.terminal_growth == Decimal("0.0425")
    assert {item.role for item in result.inputs.evidence} == {
        "beta",
        "equity_risk_premium",
        "pre_tax_cost_of_debt",
        "debt_weight",
        "equity_weight",
        "risk_free_rate",
        "terminal_growth",
    }
    assert result.reference_selection is not None
    assert result.reference_selection_digest == result.reference_selection.output_digest
    assert result.terminal_selection is not None
    assert result.terminal_selection_digest == result.terminal_selection.output_digest
    repeated = evaluate_automatic_market_policy(
        decision,
        policy=_market_policy(AT),
        admissions=(*reversed(admissions), admissions[0]),
        expected=result,
    )
    assert canonical_bytes(repeated) == canonical_bytes(result)


@pytest.mark.parametrize(
    "metric,code",
    [
        ("us.nominal_gdp", "TERMINAL_GDP_SOURCE_UNAVAILABLE"),
        ("us.treasury_par_yield_10y", "MARKET_RATE_SOURCE_UNAVAILABLE"),
        ("industry.equity_beta", "MARKET_REFERENCE_SOURCE_UNAVAILABLE"),
    ],
)
def test_missing_role_refuses_without_partial_inputs(metric, code):
    admissions = tuple(
        item for item in _admissions(AT) if item.request.metric_id != metric
    )
    result = evaluate_automatic_market_policy(
        _plan_decision(), policy=_market_policy(AT), admissions=admissions
    )
    assert result.status == "refused"
    assert result.inputs is None
    assert code in result.issue_codes


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer_id": "0000909724"},
        {"valuation_at": AT - timedelta(days=1)},
        {"policy_id": "different-model-policy"},
    ],
)
def test_terminal_policy_cannot_use_a_different_context(changes):
    policy = _market_policy(AT)
    policy = policy.model_copy(
        update={
            "terminal_growth_plan": policy.terminal_growth_plan.model_copy(
                update=changes
            )
        }
    )
    result = evaluate_automatic_market_policy(
        _plan_decision(), policy=policy, admissions=_admissions(AT)
    )
    assert result.status == "refused"
    assert result.issue_codes == ("TERMINAL_POLICY_CONTEXT_MISMATCH",)
    assert result.inputs is None


def test_terminal_rate_policy_must_match_the_assembly_policy():
    policy = _market_policy(AT)
    alternate_rate_policy = USD_RISK_FREE_POLICY.model_copy(
        update={"maximum_age_days": 1}
    )
    with pytest.raises(ValidationError, match="approved risk-free policy"):
        AutomaticMarketPolicyPolicyV1.model_validate(
            {
                **policy.model_dump(),
                "risk_free_policy": alternate_rate_policy,
            }
        )


def test_replay_rejects_changed_evidence_and_ignores_ambient_decimal_context():
    decision = _plan_decision()
    policy = _market_policy(AT)
    admissions = _admissions(AT)
    first = evaluate_automatic_market_policy(
        decision, policy=policy, admissions=admissions
    )
    with localcontext(Context(prec=6, traps=[Inexact])):
        repeated = evaluate_automatic_market_policy(
            decision, policy=policy, admissions=admissions, expected=first
        )
    assert canonical_bytes(repeated) == canonical_bytes(first)
    with pytest.raises(SnapshotError) as error:
        evaluate_automatic_market_policy(
            decision, policy=policy, admissions=admissions[:-1], expected=first
        )
    assert error.value.code == "AUTOMATIC_MARKET_POLICY_REPLAY_MISMATCH"
