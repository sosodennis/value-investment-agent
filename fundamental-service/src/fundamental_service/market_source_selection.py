"""Select observed market inputs from admitted, provider-neutral source evidence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import MarketPolicyInputsV1, TraceV1
from .macro_series import MacroSeriesVintageV1, select_macro_vintage
from .market_reference_selection import (
    IssuerMarketReferenceSelectionV1,
    MarketReferenceSelectionError,
    verify_market_reference_policy_evidence,
)
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest
from .source_admission import SourceAdmissionV1


class MarketSourceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DailyMarketRatePolicyV1(BaseModel):
    """Trusted selection rules; providers cannot choose currency or freshness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    maximum_age_days: int = Field(ge=0)


USD_RISK_FREE_POLICY = DailyMarketRatePolicyV1(
    policy_version="usd-treasury-10y-latest-daily-7d-v1",
    series_id="us.treasury_par_yield_10y",
    currency="USD",
    maximum_age_days=7,
)


@dataclass(frozen=True)
class SelectedMarketRateV1:
    value: Decimal
    trace: TraceV1
    input_digest: str
    output_digest: str


@using_valuation_context
def select_market_rate(
    admissions: tuple[SourceAdmissionV1, ...],
    *,
    policy: DailyMarketRatePolicyV1,
    valuation_at: datetime,
    currency: str,
) -> SelectedMarketRateV1:
    """Select latest vintage/day, convert percent to fraction, and retain lineage.

    Admissions must first be reproduced by the trusted release loader. This
    selector performs no I/O and grants no source permissions of its own.
    """
    if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        raise MarketSourceError(
            "MARKET_RATE_TIMESTAMP_INVALID", "valuation requires a timezone"
        )
    valuation_at = valuation_at.astimezone(UTC)
    if currency != policy.currency:
        raise MarketSourceError(
            "MARKET_RATE_CURRENCY_UNSUPPORTED",
            "rate policy does not support the valuation currency",
        )
    ordered = tuple(
        sorted(
            {x.output_digest: x for x in admissions}.values(),
            key=lambda x: x.output_digest,
        )
    )
    eligible = tuple(
        x
        for x in ordered
        if x.status == "admitted"
        and x.request.intended_use == "valuation_preparation"
        and isinstance(x.vintage, MacroSeriesVintageV1)
        and x.vintage.series_id == policy.series_id
        and x.vintage.available_at <= valuation_at
    )
    if not eligible:
        raise MarketSourceError(
            "MARKET_RATE_SOURCE_UNAVAILABLE",
            "no admitted preparation source is available for the rate policy",
        )
    try:
        vintage = select_macro_vintage(
            tuple(
                x.vintage
                for x in eligible
                if isinstance(x.vintage, MacroSeriesVintageV1)
            ),
            series_id=policy.series_id,
            valuation_at=valuation_at,
        )
    except ValueError as error:
        raise MarketSourceError("MARKET_RATE_SOURCE_AMBIGUOUS", str(error)) from error
    matches = tuple(x for x in eligible if x.vintage == vintage)
    if len(matches) != 1:
        raise MarketSourceError(
            "MARKET_RATE_SOURCE_AMBIGUOUS", "rate vintage has conflicting admissions"
        )
    admission = matches[0]
    if vintage.unit != "percent" or vintage.frequency != "daily":
        raise MarketSourceError(
            "MARKET_RATE_BASIS_UNSUPPORTED", "rate requires daily percent observations"
        )
    latest_day = max(x.period_end for x in vintage.observations)
    latest = tuple(x for x in vintage.observations if x.period_end == latest_day)
    if len(latest) != 1:
        raise MarketSourceError(
            "MARKET_RATE_OBSERVATION_AMBIGUOUS", "rate has conflicting latest periods"
        )
    observation = latest[0]
    if observation.period_start != observation.period_end:
        raise MarketSourceError(
            "MARKET_RATE_BASIS_UNSUPPORTED", "daily rate requires a single-day period"
        )
    if (valuation_at.date() - observation.period_end).days > policy.maximum_age_days:
        raise MarketSourceError(
            "MARKET_RATE_SOURCE_STALE", "latest observed rate exceeds the policy age"
        )
    originals = tuple(
        x for x in vintage.artifacts if x.content_sha256 == observation.source_sha256
    )
    if len(originals) != 1:
        raise MarketSourceError(
            "MARKET_RATE_ORIGINAL_AMBIGUOUS",
            "rate requires one original source identity",
        )
    original = originals[0]
    input_digest = sha256_digest(
        {
            "policy": policy,
            "valuation_at": valuation_at,
            "currency": currency,
            "admissions": ordered,
        }
    )
    value = observation.value / Decimal(100)
    as_of = datetime.combine(observation.period_end, datetime.min.time(), UTC)
    trace = TraceV1(
        source_refs=(
            original.content_sha256,
            admission.output_digest,
            vintage.content_digest,
            sha256_digest(observation),
            input_digest,
        ),
        source_ids=(original.source_id,),
        source_uris=(original.uri,),
        source_versions=(original.source_version, policy.policy_version),
        terms_references=(original.terms_reference,),
        as_of=as_of,
        available_at=vintage.available_at,
        captured_at=vintage.captured_at,
        expression="published_percent / 100",
        description="Latest eligible daily rate under the versioned selection policy",
    )
    output_digest = sha256_digest(
        {"input_digest": input_digest, "value": value, "trace": trace}
    )
    return SelectedMarketRateV1(
        value=value,
        trace=trace,
        input_digest=input_digest,
        output_digest=output_digest,
    )


def verify_observed_market_inputs(
    inputs: MarketPolicyInputsV1,
    *,
    admissions: tuple[SourceAdmissionV1, ...],
    valuation_at: datetime,
    currency: str,
    reference_selection: IssuerMarketReferenceSelectionV1 | None = None,
) -> dict[str, TraceV1]:
    """Verify observed declarations; explicit normative policies stay distinct."""
    traces = {}
    for evidence in sorted(inputs.evidence, key=lambda x: x.role):
        if evidence.method != "observed_source":
            continue
        if evidence.role == "equity_risk_premium":
            if reference_selection is None:
                raise MarketSourceError(
                    "MARKET_REFERENCE_PLAN_MISSING",
                    "observed ERP requires a deployment-pinned issuer reference plan",
                )
            try:
                traces.update(
                    verify_market_reference_policy_evidence(
                        (evidence,), selections=reference_selection.selections
                    )
                )
            except MarketReferenceSelectionError as error:
                raise MarketSourceError(error.code, str(error)) from error
            continue
        if evidence.role != "risk_free_rate":
            raise MarketSourceError(
                "MARKET_OBSERVED_ROLE_UNSUPPORTED",
                "observed market role has no configured financial selection rule",
            )
        selected = select_market_rate(
            admissions,
            policy=USD_RISK_FREE_POLICY,
            valuation_at=valuation_at,
            currency=currency,
        )
        trace = selected.trace
        if (
            evidence.value != selected.value
            or evidence.content_hash != trace.source_refs[0]
            or evidence.source_id != trace.source_ids[0]
            or evidence.source_uri != trace.source_uris[0]
            or evidence.source_version != trace.source_versions[0]
            or evidence.terms_reference != trace.terms_references[0]
            or evidence.as_of != trace.as_of
            or evidence.available_at != trace.available_at
            or evidence.captured_at != trace.captured_at
        ):
            raise MarketSourceError(
                "MARKET_POLICY_SOURCE_MISMATCH",
                "observed market input differs from the admitted selection",
            )
        traces[evidence.role] = trace.model_copy(
            update={"source_refs": (*trace.source_refs, selected.output_digest)}
        )
    return traces
