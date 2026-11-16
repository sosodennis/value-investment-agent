from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from fundamental_service.damodaran_source import (
    DAMODARAN_CAPITAL_PROFILE,
    DAMODARAN_SOURCE,
    DAMODARAN_TERMS,
    DamodaranReferenceProvider,
)
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.market_reference import (
    MarketReferenceProviderPort,
    MarketReferenceVintageV1,
    ReferenceMetric,
    ReferenceRowV1,
    reproduce_reference_vintage,
)
from fundamental_service.market_reference_selection import (
    MarketReferenceSelectionPolicyV1,
    select_market_reference,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
    admit_reference_source,
)
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1
from reference_source_fixtures import capital_xls

CAPTURE = datetime(2026, 11, 12, tzinfo=UTC)
VALUATION = CAPTURE + timedelta(days=1)
METRICS: tuple[ReferenceMetric, ...] = (
    "industry.equity_beta",
    "industry.pre_tax_cost_of_debt",
    "industry.debt_weight",
    "industry.equity_weight",
)
TERMS = RetainedSourceV1(
    source_id="synthetic-terms",
    uri="https://example.test/capital-terms",
    source_version="synthetic-terms-v1",
    terms_reference="https://example.test/capital-terms",
    content=b"Synthetic aggregate permission, for tests only",
    captured_at=CAPTURE,
)


def original(*, change: str = "") -> RetainedSourceV1:
    return RetainedSourceV1(
        source_id=DAMODARAN_SOURCE,
        uri="https://pages.stern.nyu.edu/~adamodar/pc/archives/wacc24.xls",
        source_version=DAMODARAN_CAPITAL_PROFILE,
        terms_reference=DAMODARAN_TERMS,
        content=capital_xls(change=change),
        captured_at=CAPTURE,
    )


class AlternateCapitalProvider:
    """An independent JSON shape using the same reference port and selector."""

    provider_id = "synthetic-alternate-industry-capital"

    def supports(self, metric: ReferenceMetric) -> bool:
        return metric in METRICS

    def reproduce_vintage(
        self, *, metric: ReferenceMetric, sources: tuple[RetainedSourceV1, ...]
    ) -> MarketReferenceVintageV1:
        source = sources[0]
        value = json.loads(source.content)[metric]
        digest = hashlib.sha256(source.content).hexdigest()
        return MarketReferenceVintageV1.build(
            metric=metric,
            population="us-companies",
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
                    captured_at=source.captured_at,
                    content_sha256=digest,
                ),
            ),
            rows=(
                ReferenceRowV1(
                    subject="Retail (Special Lines)",
                    subject_kind="industry",
                    value=Decimal(value),
                    missing_reason=None,
                    raw_value=value,
                    numeric_encoding="decimal_text",
                    value_basis="published_cell",
                    number_format="General",
                    locator=f"$['{metric}']",
                    source_sha256=digest,
                ),
            ),
        )


def admission(provider: MarketReferenceProviderPort, source, metric, **updates):
    rule = SourceUseRuleV1(
        rule_id="synthetic-capital-use",
        provider_id=provider.provider_id,
        metric_id=metric,
        population="us-companies",
        source_id=source.source_id,
        source_version=source.source_version,
        terms_reference=source.terms_reference,
        permitted_uses=("valuation_preparation",),
        terms=(
            TermsRequirementV1(
                uri=TERMS.uri,
                content_sha256=hashlib.sha256(TERMS.content).hexdigest(),
            ),
        ),
        required_notices=("Synthetic capital selection test only",),
        basis="Synthetic permission, no production source authority",
    )
    options = dict(
        metric=metric,
        sources=(source,),
        terms=(TERMS,),
        valuation_at=VALUATION,
        policy=SourceUsePolicyV1(policy_version="synthetic-capital-v1", rules=(rule,)),
    )
    options.update(updates)
    return admit_reference_source(provider, **options)


@pytest.mark.parametrize(
    "metric,column,value,unit",
    [
        ("industry.equity_beta", "C", 1.23, "multiple"),
        ("industry.pre_tax_cost_of_debt", "G", 0.0578, "fraction"),
        ("industry.debt_weight", "J", 0.225, "fraction"),
        ("industry.equity_weight", "E", 0.775, "fraction"),
    ],
)
def test_capital_preserves_exact_pretax_columns_precision_and_source_scope(
    metric, column, value, unit
):
    source = original()
    result = reproduce_reference_vintage(
        DamodaranReferenceProvider(), metric=metric, sources=(source,)
    )
    retail = next(x for x in result.rows if x.subject == "Retail (Special Lines)")
    assert retail.value == Decimal.from_float(value)
    assert retail.raw_value == value.hex()
    assert retail.locator == f"Industry Averages!{column}20"
    assert retail.value_basis == "published_biff_cache"
    assert retail.source_sha256 == hashlib.sha256(source.content).hexdigest()
    assert result.unit == unit
    assert result.population == "us-companies"
    assert result.source_updated_on == date(2025, 1, 5)
    assert result.available_at == result.captured_at == CAPTURE
    context = {x.name: x for x in result.context}
    assert "regression beta" in context["beta_method"].raw_value
    assert "including lease debt" in context["capital_weight_method"].raw_value
    assert "for sector" in context["debt_cost_method"].raw_value
    assert context["reference_marginal_tax"].raw_value == float(0.25).hex()
    assert all(x.source_sha256 == retail.source_sha256 for x in result.context)
    assert any(x.subject_kind == "aggregate" for x in result.rows)
    missing = next(x for x in result.rows if x.subject == "Missing industry")
    assert missing.value is None
    assert missing.missing_reason == "empty_cell"


@pytest.mark.parametrize(
    "change",
    [
        "header",
        "currency",
        "population",
        "tax_basis",
        "future",
        "context_domain",
        "gap",
        "duplicate",
        "domain",
        "precision",
        "method",
    ],
)
def test_changed_capital_originals_retain_source_and_repeat_the_same_refusal(change):
    source = original(change=change)
    first = admission(
        DamodaranReferenceProvider(),
        source,
        "industry.debt_weight"
        if change == "domain"
        else "industry.pre_tax_cost_of_debt",
    )
    repeat = admission(DamodaranReferenceProvider(), source, first.request.metric_id)
    assert first.status == "refused"
    assert first.vintage is None
    assert first.issue_codes == (
        "REFERENCE_SOURCE_INVALID",
        "SOURCE_REPRODUCTION_FAILED",
    )
    assert (
        first.request.source_artifacts[0].content_sha256
        == hashlib.sha256(source.content).hexdigest()
    )
    assert canonical_bytes(first) == canonical_bytes(repeat)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content", b"corrupt workbook"),
        ("source_id", "unconfigured"),
        ("source_version", "unreviewed-profile"),
        ("terms_reference", "unconfigured-terms"),
        ("uri", "https://example.test/wacc24.xls"),
        ("uri", "https://pages.stern.nyu.edu/~adamodar/pc/archives/betas24.xls"),
    ],
)
def test_capital_rejects_profile_or_source_substitution(field, value):
    source = replace(original(), **{field: value})
    result = admission(DamodaranReferenceProvider(), source, "industry.equity_beta")
    assert result.status == "refused"
    assert "SOURCE_REPRODUCTION_FAILED" in result.issue_codes
    assert (
        result.request.source_artifacts[0].content_sha256
        == hashlib.sha256(source.content).hexdigest()
    )


@pytest.mark.parametrize("metric", METRICS)
def test_second_provider_uses_the_same_selector_without_provider_specific_branches(
    metric,
):
    first = admission(DamodaranReferenceProvider(), original(), metric)
    expected = next(
        x.value for x in first.vintage.rows if x.subject == "Retail (Special Lines)"
    )
    alternative = RetainedSourceV1(
        source_id="synthetic-json-reference",
        uri="https://example.test/capital.json",
        source_version="synthetic-json-v1",
        terms_reference=TERMS.uri,
        content=canonical_bytes({metric: str(expected)}),
        captured_at=CAPTURE,
    )
    second = admission(AlternateCapitalProvider(), alternative, metric)
    policy = MarketReferenceSelectionPolicyV1(
        policy_version="synthetic-exact-industry-v1",
        metric=metric,
        population="us-companies",
        subject_kind="industry",
        subject="Retail (Special Lines)",
        maximum_age_days=730,
    )
    left = select_market_reference((first,), policy=policy, valuation_at=VALUATION)
    right = select_market_reference((second,), policy=policy, valuation_at=VALUATION)
    assert left.status == right.status == "selected"
    assert left.value == right.value == expected
    assert left.trace.source_refs[0] == hashlib.sha256(original().content).hexdigest()
    assert right.trace.source_refs[0] == hashlib.sha256(alternative.content).hexdigest()
    assert left.output_digest != right.output_digest
    missing = select_market_reference(
        (first,),
        policy=policy.model_copy(update={"subject": "Missing industry"}),
        valuation_at=VALUATION,
    )
    assert missing.status == "refused"
    assert missing.row.missing_reason == "empty_cell"
    assert missing.trace is None


@pytest.mark.parametrize("metric", METRICS)
def test_capital_repeat_is_canonical_and_independent_of_ambient_decimal_context(metric):
    source = original()
    first = admission(DamodaranReferenceProvider(), source, metric)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        repeat = admission(DamodaranReferenceProvider(), source, metric)
    assert canonical_bytes(first) == canonical_bytes(repeat)
    assert first.output_digest == repeat.output_digest
    assert first.vintage == MarketReferenceVintageV1.model_validate_json(
        canonical_bytes(first.vintage)
    )


@pytest.mark.parametrize("metric", METRICS)
def test_capital_does_not_backdate_availability_or_grant_company_evidence(metric):
    source = original()
    result = admission(
        DamodaranReferenceProvider(),
        source,
        metric,
        valuation_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert result.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    assert result.vintage.available_at == CAPTURE
    production = admission(
        DamodaranReferenceProvider(), source, metric, policy=free_market_source_policy()
    )
    assert production.status == "refused"
    assert production.issue_codes == ("SOURCE_USE_TERMS_MISSING",)
    rules = [x for x in free_market_source_policy().rules if x.metric_id == metric]
    assert len(rules) == 1
    assert rules[0].source_version == DAMODARAN_CAPITAL_PROFILE
    assert rules[0].population == "us-companies"
    assert rules[0].permitted_uses == (
        "valuation_preparation",
        "derived_valuation_display",
    )
    assert "company-level" in rules[0].required_notices[0]


@pytest.mark.parametrize(
    "metric,value,accepted",
    [
        ("industry.pre_tax_cost_of_debt", "0", True),
        ("industry.pre_tax_cost_of_debt", "1", False),
        ("industry.pre_tax_cost_of_debt", "-0.01", False),
        ("industry.debt_weight", "0", True),
        ("industry.debt_weight", "1", True),
        ("industry.debt_weight", "1.01", False),
        ("industry.equity_weight", "0", True),
        ("industry.equity_weight", "1", True),
        ("industry.equity_weight", "-0.01", False),
    ],
)
def test_provider_neutral_domains_allow_unlevered_or_all_debt_capital(
    metric, value, accepted
):
    source = RetainedSourceV1(
        source_id="synthetic-json-reference",
        uri="https://example.test/capital.json",
        source_version="synthetic-json-v1",
        terms_reference=TERMS.uri,
        content=canonical_bytes({metric: value}),
        captured_at=CAPTURE,
    )
    result = admission(AlternateCapitalProvider(), source, metric)
    assert result.status == ("admitted" if accepted else "refused")
    if accepted:
        assert result.vintage.rows[0].value == Decimal(value)
    else:
        assert result.vintage is None
        assert "SOURCE_REPRODUCTION_FAILED" in result.issue_codes
