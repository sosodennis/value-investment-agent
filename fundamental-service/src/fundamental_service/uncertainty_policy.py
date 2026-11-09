"""Service-owned uncertainty policy for automatic FCFF valuation."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from statistics import mean

from .contracts import (
    DistributionParameterV1,
    DistributionProvenanceV1,
    UncertaintyV1,
    ValuationInputV1,
)
from .serialization import sha256_digest

DEFAULT_UNCERTAINTY_POLICY_VERSION = "fcff-monte-carlo-policy-v1"
DEFAULT_SAMPLER_VERSION = "python-random-v1"
DEFAULT_SAMPLE_COUNT = 256
DEFAULT_INVALID_DRAW_POLICY = "skip"

_EMPIRICAL_MINIMUMS = {
    "revenue_growth": 3,
    "operating_margin": 4,
    "reinvestment_rate": 3,
}
_DOMAIN_BOUNDS = {
    "revenue_growth": (Decimal("-0.90"), Decimal("1.00")),
    "operating_margin": (Decimal("-1.00"), Decimal("1.00")),
    "reinvestment_rate": (Decimal("-1.00"), Decimal("1.00")),
}
_PRIOR_BOUNDS = {
    "revenue_growth": (Decimal("-0.20"), Decimal("0.20")),
    "operating_margin": (Decimal("-0.10"), Decimal("0.40")),
    "reinvestment_rate": (Decimal("0.00"), Decimal("1.00")),
    "terminal_growth": (Decimal("0.00"), Decimal("0.04")),
}


def _records(metrics: Iterable[object], metric_id: str) -> tuple[object, ...]:
    return tuple(
        item for item in metrics if getattr(item, "metric_id", None) == metric_id
    )


def _bounded(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return min(upper, max(lower, value))


def _empirical_parameter(
    metric_id: str,
    records: tuple[object, ...],
    *,
    path: str,
) -> DistributionParameterV1:
    values = tuple(getattr(item, "value") for item in records)
    domain_lower, domain_upper = _DOMAIN_BOUNDS[metric_id]
    observed_lower = min(values)
    observed_upper = max(values)
    span = observed_upper - observed_lower
    padding = max(Decimal("0.02"), span * Decimal("0.10"))
    lower = _bounded(observed_lower - padding, domain_lower, domain_upper)
    upper = _bounded(observed_upper + padding, domain_lower, domain_upper)
    if lower == upper:
        lower = _bounded(lower - Decimal("0.02"), domain_lower, domain_upper)
        upper = _bounded(upper + Decimal("0.02"), domain_lower, domain_upper)
    provenance = DistributionProvenanceV1(
        source_kind="empirical_history",
        historical_periods=tuple(
            sorted(getattr(item, "fiscal_year") for item in records)
        ),
        source_fact_ids=tuple(
            sorted(
                {
                    fact_id
                    for item in records
                    for fact_id in getattr(item, "fact_ids", ())
                }
            )
        ),
        estimation_method="bounded_empirical_triangular_v1",
        rationale=(
            f"bounded triangular estimate from {len(records)} comparable "
            f"annual {metric_id} observations"
        ),
    )
    return DistributionParameterV1(
        path=path,
        distribution="triangular",
        lower=lower,
        upper=upper,
        mode=_bounded(Decimal(str(mean(values))), lower, upper),
        provenance=provenance,
    )


def _policy_prior(
    metric_id: str,
    *,
    path: str,
    mode: Decimal,
    policy_version: str,
) -> DistributionParameterV1:
    lower, upper = _PRIOR_BOUNDS[metric_id]
    bounded_mode = _bounded(mode, lower, upper)
    return DistributionParameterV1(
        path=path,
        distribution="triangular",
        lower=lower,
        upper=upper,
        mode=bounded_mode,
        provenance=DistributionProvenanceV1(
            source_kind="policy_prior",
            estimation_method="approved_bounded_triangular_prior_v1",
            policy_version=policy_version,
            rationale=(
                f"approved bounded prior for {metric_id} when comparable history "
                "does not meet the empirical eligibility gate"
            ),
        ),
    )


def _metric_parameter(
    metric_id: str,
    records: tuple[object, ...],
    *,
    path: str,
    base_value: Decimal,
    policy_version: str,
) -> DistributionParameterV1:
    if len(records) >= _EMPIRICAL_MINIMUMS[metric_id]:
        return _empirical_parameter(metric_id, records, path=path)
    return _policy_prior(
        metric_id,
        path=path,
        mode=base_value,
        policy_version=policy_version,
    )


def build_default_uncertainty(
    request: ValuationInputV1,
    *,
    historical_metrics: Iterable[object],
    policy_version: str = DEFAULT_UNCERTAINTY_POLICY_VERSION,
) -> UncertaintyV1:
    """Build the canonical Monte Carlo controls for an automatic request."""

    if request.assumptions.forecast is None or request.assumptions.wacc is None:
        raise ValueError("automatic uncertainty requires FCFF assumptions")
    metric_items = tuple(historical_metrics)
    forecast = request.assumptions.forecast
    parameters = (
        _metric_parameter(
            "revenue_growth",
            _records(metric_items, "revenue_growth"),
            path="assumptions.forecast.revenue_growth[0]",
            base_value=forecast.revenue_growth[0],
            policy_version=policy_version,
        ),
        _metric_parameter(
            "operating_margin",
            _records(metric_items, "operating_margin"),
            path="assumptions.forecast.operating_margin[0]",
            base_value=forecast.operating_margin[0],
            policy_version=policy_version,
        ),
        _metric_parameter(
            "reinvestment_rate",
            _records(metric_items, "reinvestment_rate"),
            path="assumptions.forecast.reinvestment_rate[0]",
            base_value=forecast.reinvestment_rate[0],
            policy_version=policy_version,
        ),
        _policy_prior(
            "terminal_growth",
            path="assumptions.terminal_growth",
            mode=request.assumptions.terminal_growth,
            policy_version=policy_version,
        ),
    )
    base_digest = request.with_digest().input_digest
    assert base_digest is not None
    seed_digest = sha256_digest(
        {
            "base_input_digest": base_digest,
            "policy_version": policy_version,
            "sampler_version": DEFAULT_SAMPLER_VERSION,
        }
    )
    return UncertaintyV1(
        mode="monte_carlo",
        parameters=parameters,
        samples=DEFAULT_SAMPLE_COUNT,
        seed=int(seed_digest[:16], 16),
        policy_version=policy_version,
        invalid_draw_policy=DEFAULT_INVALID_DRAW_POLICY,
    )


__all__ = [
    "DEFAULT_INVALID_DRAW_POLICY",
    "DEFAULT_SAMPLE_COUNT",
    "DEFAULT_SAMPLER_VERSION",
    "DEFAULT_UNCERTAINTY_POLICY_VERSION",
    "build_default_uncertainty",
]
