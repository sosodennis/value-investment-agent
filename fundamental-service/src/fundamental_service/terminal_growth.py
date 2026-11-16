"""Source-neutral stable-growth policy; this is an assumption, not a forecast."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import MarketPolicyEvidenceV1, StrictModel, TraceV1
from .macro_series import (
    MacroSeriesVintageV1,
    NominalGdpGrowthCeilingV1,
    select_macro_vintage,
)
from .market_source_selection import (
    DailyMarketRatePolicyV1,
    MarketSourceError,
    select_market_rate,
)
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest
from .source_admission import SourceAdmissionV1


class TerminalGrowthPlanV1(StrictModel):
    protocol: Literal["nominal-gdp-riskfree-ceiling-v1"] = (
        "nominal-gdp-riskfree-ceiling-v1"
    )
    issuer_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    valuation_at: datetime
    currency: Literal["USD"] = "USD"
    gdp_horizon_years: int = Field(ge=1, le=100)
    maximum_gdp_period_age_days: int = Field(ge=0)
    risk_free_policy: DailyMarketRatePolicyV1

    @field_validator("valuation_at")
    @classmethod
    def aware_valuation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("terminal policy requires a valuation timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def compatible_rate(self) -> "TerminalGrowthPlanV1":
        if (
            self.risk_free_policy.currency != self.currency
            or self.risk_free_policy.series_id != "us.treasury_par_yield_10y"
        ):
            raise ValueError("terminal policy requires the USD long-term rate metric")
        return self


class TerminalGrowthSelectionV1(StrictModel):
    plan: TerminalGrowthPlanV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: Decimal = Field(allow_inf_nan=False)
    gdp_ceiling: NominalGdpGrowthCeilingV1
    risk_free_value: Decimal = Field(allow_inf_nan=False)
    risk_free_selection_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace: TraceV1
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bounded_content(self) -> "TerminalGrowthSelectionV1":
        if self.value != min(self.risk_free_value, self.gdp_ceiling.nominal_gdp_cagr):
            raise ValueError("terminal assumption differs from its executable rule")
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("terminal selection digest does not match content")
        return self


@using_valuation_context
def select_terminal_growth(
    plan: TerminalGrowthPlanV1, *, admissions: tuple[SourceAdmissionV1, ...]
) -> TerminalGrowthSelectionV1:
    """Use the latest admitted GDP vintage and rate without filling missing data."""
    ordered = tuple(
        sorted(
            {item.output_digest: item for item in admissions}.values(),
            key=lambda item: item.output_digest,
        )
    )
    candidates = tuple(
        item.vintage
        for item in ordered
        if item.status == "admitted"
        and item.request.intended_use == "valuation_preparation"
        and isinstance(item.vintage, MacroSeriesVintageV1)
        and item.vintage.series_id == "us.nominal_gdp"
    )
    try:
        vintage = select_macro_vintage(
            candidates, series_id="us.nominal_gdp", valuation_at=plan.valuation_at
        )
    except ValueError as error:
        raise MarketSourceError(
            "TERMINAL_GDP_SOURCE_UNAVAILABLE", str(error)
        ) from error
    try:
        ceiling = NominalGdpGrowthCeilingV1.derive(
            vintage,
            valuation_at=plan.valuation_at,
            horizon_years=plan.gdp_horizon_years,
        )
    except ValueError as error:
        raise MarketSourceError(
            "TERMINAL_GDP_HORIZON_UNAVAILABLE", str(error)
        ) from error
    age = (plan.valuation_at.date() - date(ceiling.end_year, 12, 31)).days
    if age > plan.maximum_gdp_period_age_days:
        raise MarketSourceError(
            "TERMINAL_GDP_PERIOD_STALE", "latest annual GDP period is stale"
        )
    rate = select_market_rate(
        ordered,
        policy=plan.risk_free_policy,
        valuation_at=plan.valuation_at,
        currency=plan.currency,
    )
    assert rate.trace.as_of is not None
    assert rate.trace.available_at is not None
    assert rate.trace.captured_at is not None
    originals = tuple(sorted(vintage.artifacts, key=lambda x: (x.source_id, x.uri)))
    input_digest = sha256_digest({"plan": plan, "admissions": ordered})
    payload = {
        "plan": plan,
        "input_digest": input_digest,
        "value": min(rate.value, ceiling.nominal_gdp_cagr),
        "gdp_ceiling": ceiling,
        "risk_free_value": rate.value,
        "risk_free_selection_digest": rate.output_digest,
        "trace": TraceV1(
            expression="min(nominal_gdp_cagr, long_term_risk_free_rate)",
            inputs=(ceiling.content_digest, rate.output_digest, sha256_digest(plan)),
            source_refs=tuple(
                sorted(
                    {
                        *rate.trace.source_refs,
                        *(item.content_sha256 for item in originals),
                        ceiling.content_digest,
                        rate.output_digest,
                        sha256_digest(plan),
                        input_digest,
                    }
                )
            ),
            source_ids=tuple(
                sorted(
                    {*rate.trace.source_ids, *(item.source_id for item in originals)}
                )
            ),
            source_uris=tuple(
                sorted({*rate.trace.source_uris, *(item.uri for item in originals)})
            ),
            source_versions=tuple(
                sorted(
                    {
                        *rate.trace.source_versions,
                        *(x.source_version for x in originals),
                    }
                )
            ),
            terms_references=tuple(
                sorted(
                    {
                        *rate.trace.terms_references,
                        *(x.terms_reference for x in originals),
                    }
                )
            ),
            as_of=rate.trace.as_of,
            available_at=max(rate.trace.available_at, vintage.available_at),
            captured_at=max(rate.trace.captured_at, vintage.captured_at),
            description="Explicit stable-growth policy assumption bounded by nominal "
            "GDP and long-term risk-free rate; not observed issuer growth or a "
            "history-sufficiency conclusion.",
        ),
    }
    return TerminalGrowthSelectionV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )


def terminal_growth_evidence(
    selection: TerminalGrowthSelectionV1,
) -> MarketPolicyEvidenceV1:
    """Describe a reproduced policy assumption without relabeling it as observed."""
    trace = selection.trace
    assert trace.as_of is not None
    assert trace.available_at is not None
    assert trace.captured_at is not None
    return MarketPolicyEvidenceV1(
        role="terminal_growth",
        method="approved_policy",
        value=selection.value,
        source_id="terminal-growth:" + selection.plan.protocol,
        source_uri="urn:fundamental:terminal-growth:" + selection.plan.protocol,
        content_hash=selection.output_digest,
        source_version=selection.plan.protocol,
        terms_reference="deployment-policy:" + selection.plan.policy_id,
        as_of=trace.as_of,
        available_at=trace.available_at,
        captured_at=trace.captured_at,
        rationale=trace.description or "Explicit bounded stable-growth assumption",
    )
