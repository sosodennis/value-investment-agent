from __future__ import annotations

from collections.abc import Callable

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ....report_contract import FinancialReport, FinancialServicesExtension
from ...core_ops_service import ratio_with_optional_inputs

DEFAULT_BANK_RORWA = 0.03


def to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def bank_rorwa_observations(reports: list[FinancialReport]) -> list[float]:
    observations: list[float] = []
    for report in reports:
        extension = (
            report.extension
            if isinstance(report.extension, FinancialServicesExtension)
            else None
        )
        if extension is None:
            continue
        net_income = to_float(report.base.net_income.value)
        rwa = to_float(extension.risk_weighted_assets.value)
        if net_income is None or rwa in (None, 0):
            continue
        value = net_income / rwa
        if value > 0:
            observations.append(float(value))
    return observations


def bank_rwa_observations(reports: list[FinancialReport]) -> list[float]:
    observations: list[float] = []
    for report in reports:
        extension = (
            report.extension
            if isinstance(report.extension, FinancialServicesExtension)
            else None
        )
        if extension is None:
            continue
        rwa = to_float(extension.risk_weighted_assets.value)
        if rwa is None or rwa <= 0:
            continue
        observations.append(float(rwa))
    return observations


def is_bank_rorwa_outlier(value: float, baseline: float | None) -> bool:
    # Typical bank return-on-RWA range is low single-digit %. Extreme values
    # usually indicate tag/context mismatch rather than real economics.
    if value <= 0 or value > 0.20:
        return True
    if baseline is None or baseline <= 0:
        return False
    return value > baseline * 3.0 or value < baseline / 3.0


def is_bank_rwa_discontinuous(value: float, baseline: float | None) -> bool:
    if value <= 0:
        return True
    if baseline is None or baseline <= 0:
        return False
    return value > baseline * 3.0 or value < baseline / 3.0


def build_bank_rorwa_intensity(
    *,
    reports: list[FinancialReport],
    net_income_tf: TraceableField[float],
    rwa_tf: TraceableField[float] | None,
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    missing_field: Callable[[str, str], TraceableField[float]],
    assumptions: list[str],
) -> TraceableField[float]:
    latest_rorwa_tf = ratio_with_optional_inputs(
        name="RoRWA",
        numerator=net_income_tf,
        denominator=rwa_tf,
        expression="NetIncome / RiskWeightedAssets",
        missing_reason="Missing Risk-Weighted Assets",
        ratio_op=ratio,
        missing_field_op=missing_field,
    )
    baseline_rorwa = median(bank_rorwa_observations(reports[1:]))
    baseline_rwa = median(bank_rwa_observations(reports[1:]))
    latest_rwa = to_float(rwa_tf.value) if rwa_tf is not None else None

    if latest_rorwa_tf.value is None:
        if baseline_rorwa is not None:
            assumptions.append("rwa_intensity fallback to historical median RoRWA")
            return TraceableField(
                name="RoRWA",
                value=baseline_rorwa,
                provenance=ManualProvenance(
                    description=(
                        "Latest RoRWA unavailable; fell back to historical median RoRWA"
                    ),
                    author="ValuationPolicy",
                ),
            )
        assumptions.append(
            f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} (RoRWA)"
        )
        return TraceableField(
            name="RoRWA",
            value=DEFAULT_BANK_RORWA,
            provenance=ManualProvenance(
                description=(
                    "RoRWA unavailable; using conservative default RoRWA for bank DDM"
                ),
                author="ValuationPolicy",
            ),
        )

    latest_rorwa = float(latest_rorwa_tf.value)
    if is_bank_rwa_discontinuous(latest_rwa or 0.0, baseline_rwa):
        if baseline_rorwa is not None:
            assumptions.append(
                "rwa_intensity fallback to historical median RoRWA "
                "(latest RWA discontinuity)"
            )
            return TraceableField(
                name="RoRWA",
                value=baseline_rorwa,
                provenance=ManualProvenance(
                    description=(
                        "Latest Risk-Weighted Assets flagged as discontinuous; "
                        "using historical median RoRWA"
                    ),
                    author="ValuationPolicy",
                ),
            )
        assumptions.append(
            f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} "
            "(latest RWA discontinuity)"
        )
        return TraceableField(
            name="RoRWA",
            value=DEFAULT_BANK_RORWA,
            provenance=ManualProvenance(
                description=(
                    "Latest Risk-Weighted Assets flagged as discontinuous; "
                    "using conservative default RoRWA"
                ),
                author="ValuationPolicy",
            ),
        )

    if is_bank_rorwa_outlier(latest_rorwa, baseline_rorwa):
        if baseline_rorwa is not None:
            assumptions.append(
                "rwa_intensity fallback to historical median RoRWA (latest outlier)"
            )
            return TraceableField(
                name="RoRWA",
                value=baseline_rorwa,
                provenance=ManualProvenance(
                    description=(
                        "Latest RoRWA flagged as outlier; using historical median RoRWA"
                    ),
                    author="ValuationPolicy",
                ),
            )
        assumptions.append(
            f"rwa_intensity defaulted to {DEFAULT_BANK_RORWA:.2%} (RoRWA outlier)"
        )
        return TraceableField(
            name="RoRWA",
            value=DEFAULT_BANK_RORWA,
            provenance=ManualProvenance(
                description=(
                    "Latest RoRWA flagged as outlier; using conservative default RoRWA"
                ),
                author="ValuationPolicy",
            ),
        )

    return latest_rorwa_tf
