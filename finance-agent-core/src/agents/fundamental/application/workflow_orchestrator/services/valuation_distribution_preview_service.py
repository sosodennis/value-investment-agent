from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject


def extract_distribution_summary(
    calculation_metrics: JSONObject,
) -> JSONObject | None:
    direct = calculation_metrics.get("distribution_summary")
    if isinstance(direct, dict):
        return direct

    details = calculation_metrics.get("details")
    if not isinstance(details, dict):
        return None
    nested = details.get("distribution_summary")
    if isinstance(nested, dict):
        return nested
    return None


def build_distribution_scenarios(
    distribution_summary: JSONObject | None,
    *,
    shares_outstanding: float | None,
) -> JSONObject | None:
    if distribution_summary is None:
        return None
    summary = distribution_summary.get("summary")
    if not isinstance(summary, dict):
        return None

    bear = coerce_float(summary.get("percentile_5"))
    base = coerce_float(summary.get("median"))
    bull = coerce_float(summary.get("percentile_95"))
    if not (
        isinstance(bear, float) and isinstance(base, float) and isinstance(bull, float)
    ):
        return None

    metric_type = _extract_distribution_metric_type(distribution_summary)
    if metric_type in {"equity_value_total", "equity_value"}:
        if shares_outstanding is None or shares_outstanding <= 0:
            return None
        bear = bear / shares_outstanding
        base = base / shares_outstanding
        bull = bull / shares_outstanding

    return {
        "bear": {"label": "P5 (Bear)", "price": bear},
        "base": {"label": "P50 (Base)", "price": base},
        "bull": {"label": "P95 (Bull)", "price": bull},
    }


def resolve_preview_valuation_metrics(
    *,
    calculation_metrics: Mapping[str, object],
    params_dump: Mapping[str, object],
    distribution_summary: Mapping[str, object] | None,
) -> tuple[float | None, float | None, float | None]:
    equity_value = _extract_numeric_metric(calculation_metrics, "equity_value")
    intrinsic_value = _extract_numeric_metric(calculation_metrics, "intrinsic_value")
    upside_potential = _extract_numeric_metric(calculation_metrics, "upside_potential")

    if intrinsic_value is None:
        intrinsic_value = _extract_numeric_metric(
            calculation_metrics, "fair_value_per_share"
        )

    shares_outstanding = coerce_float(params_dump.get("shares_outstanding"))
    current_price = coerce_float(params_dump.get("current_price"))

    if intrinsic_value is None and distribution_summary is not None:
        summary_raw = distribution_summary.get("summary")
        if isinstance(summary_raw, Mapping):
            median = coerce_float(summary_raw.get("median"))
            if median is not None:
                metric_type = _extract_distribution_metric_type(distribution_summary)
                if metric_type in {"equity_value_total", "equity_value"}:
                    if shares_outstanding is not None and shares_outstanding > 0:
                        intrinsic_value = median / shares_outstanding
                else:
                    intrinsic_value = median

    if (
        intrinsic_value is None
        and equity_value is not None
        and shares_outstanding is not None
        and shares_outstanding > 0
    ):
        intrinsic_value = equity_value / shares_outstanding

    if (
        equity_value is None
        and intrinsic_value is not None
        and shares_outstanding is not None
        and shares_outstanding > 0
    ):
        equity_value = intrinsic_value * shares_outstanding

    if (
        upside_potential is None
        and intrinsic_value is not None
        and current_price is not None
        and current_price > 0
    ):
        upside_potential = (intrinsic_value - current_price) / current_price

    return equity_value, intrinsic_value, upside_potential


def coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, Mapping):
        return coerce_float(value.get("value"))
    return None


def _extract_numeric_metric(
    calculation_metrics: Mapping[str, object],
    key: str,
) -> float | None:
    value = coerce_float(calculation_metrics.get(key))
    if value is not None:
        return value

    details = calculation_metrics.get("details")
    if isinstance(details, Mapping):
        detail_value = coerce_float(details.get(key))
        if detail_value is not None:
            return detail_value
    return None


def _extract_distribution_metric_type(
    distribution_summary: Mapping[str, object],
) -> str | None:
    raw = distribution_summary.get("metric_type")
    if isinstance(raw, str) and raw:
        return raw
    return None
