from __future__ import annotations

from datetime import datetime, timezone

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportLike,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalEvidence,
    ForwardSignalPayload,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

_SEC_SEARCH_URL_TEMPLATE = "https://www.sec.gov/edgar/search/#/entityName={ticker}"


def extract_forward_signals_from_xbrl_reports(
    *,
    ticker: str,
    reports: list[FinancialReportLike],
) -> list[dict[str, object]]:
    """
    Build conservative forward signals from SEC XBRL report trends.

    This producer is intentionally deterministic and bounded:
    - Only emits growth/margin outlook signals for v1 policy.
    - Uses acceleration / delta trends instead of absolute levels to avoid
      over-amplifying historical extrapolation.
    - Provides evidence payload for auditability.
    """
    if not reports:
        return []

    series = _build_yearly_series(reports)
    if len(series) < 2:
        return []

    signals: list[dict[str, object]] = []
    signals.extend(_build_growth_acceleration_signal(ticker=ticker, series=series))
    signals.extend(_build_margin_delta_signal(ticker=ticker, series=series))

    if signals:
        log_event(
            logger,
            event="fundamental_forward_signal_producer_completed",
            message="forward signal producer generated signals from xbrl trend data",
            fields={
                "ticker": ticker,
                "signal_count": len(signals),
                "metrics": [str(item.get("metric")) for item in signals],
            },
        )
    return signals


def _build_growth_acceleration_signal(
    *,
    ticker: str,
    series: list[tuple[int, float | None, float | None]],
) -> list[dict[str, object]]:
    revenue_points = [(year, revenue) for year, revenue, _margin in series]
    revenue_points = [item for item in revenue_points if _is_valid_positive(item[1])]
    if len(revenue_points) < 3:
        return []

    (year0, rev0), (year1, rev1), (year2, rev2) = revenue_points[-3:]
    if rev0 is None or rev1 is None or rev2 is None:
        return []

    prev_growth = (rev1 - rev0) / abs(rev0)
    curr_growth = (rev2 - rev1) / abs(rev1)
    acceleration = curr_growth - prev_growth
    if abs(acceleration) < 0.01:
        return []

    direction = "up" if acceleration > 0 else "down"
    magnitude_basis_points = _clamp(abs(acceleration) * 10_000.0 * 0.5, 25.0, 220.0)
    growth_prev_pct = prev_growth * 100.0
    growth_curr_pct = curr_growth * 100.0
    snippet = (
        f"Revenue growth changed from FY{year1} vs FY{year0}: "
        f"{growth_prev_pct:.2f}% to FY{year2} vs FY{year1}: {growth_curr_pct:.2f}%."
    )
    return [
        _signal_payload(
            signal_id=f"sec_xbrl_growth_{year2}",
            source_type="xbrl_auto",
            metric="growth_outlook",
            direction=direction,
            value=magnitude_basis_points,
            confidence=0.62,
            ticker=ticker,
            doc_type="10-K_XBRL",
            period=f"FY{year2}",
            snippet=snippet,
        )
    ]


def _build_margin_delta_signal(
    *,
    ticker: str,
    series: list[tuple[int, float | None, float | None]],
) -> list[dict[str, object]]:
    margin_points = [(year, margin) for year, _revenue, margin in series]
    margin_points = [item for item in margin_points if item[1] is not None]
    if len(margin_points) < 2:
        return []

    (prev_year, prev_margin), (curr_year, curr_margin) = margin_points[-2:]
    if prev_margin is None or curr_margin is None:
        return []

    delta = curr_margin - prev_margin
    if abs(delta) < 0.0025:
        return []

    direction = "up" if delta > 0 else "down"
    magnitude_basis_points = _clamp(abs(delta) * 10_000.0 * 0.75, 25.0, 180.0)
    snippet = (
        f"Operating margin changed from FY{prev_year}: {prev_margin * 100.0:.2f}% "
        f"to FY{curr_year}: {curr_margin * 100.0:.2f}%."
    )
    return [
        _signal_payload(
            signal_id=f"sec_xbrl_margin_{curr_year}",
            source_type="xbrl_auto",
            metric="margin_outlook",
            direction=direction,
            value=magnitude_basis_points,
            confidence=0.60,
            ticker=ticker,
            doc_type="10-K_XBRL",
            period=f"FY{curr_year}",
            snippet=snippet,
        )
    ]


def _build_yearly_series(
    reports: list[FinancialReportLike],
) -> list[tuple[int, float | None, float | None]]:
    points: list[tuple[int, float | None, float | None]] = []
    for report in reports:
        year = _to_int(report.base.fiscal_year.value)
        if year is None:
            continue
        revenue = _to_float(report.base.total_revenue.value)
        operating_income = _to_float(report.base.operating_income.value)
        margin: float | None = None
        if _is_valid_positive(revenue) and operating_income is not None:
            margin = operating_income / revenue
        points.append((year, revenue, margin))
    points.sort(key=lambda item: item[0])
    return points


def _signal_payload(
    *,
    signal_id: str,
    source_type: str,
    metric: str,
    direction: str,
    value: float,
    confidence: float,
    ticker: str,
    doc_type: str,
    period: str,
    snippet: str,
) -> dict[str, object]:
    as_of = datetime.now(timezone.utc).isoformat()
    source_url = _SEC_SEARCH_URL_TEMPLATE.format(ticker=ticker)
    payload = ForwardSignalPayload(
        signal_id=signal_id,
        source_type=source_type,
        metric=metric,
        direction=direction,
        value=round(value, 2),
        unit="basis_points",
        confidence=confidence,
        as_of=as_of,
        evidence=[
            ForwardSignalEvidence(
                preview_text=snippet,
                full_text=snippet,
                source_url=source_url,
                doc_type=doc_type,
                period=period,
            )
        ],
    )
    return payload.model_dump(exclude_none=True)


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(normalized)
        except ValueError:
            return None
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _is_valid_positive(value: float | None) -> bool:
    return value is not None and value > 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
