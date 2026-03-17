from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.subdomains.patterns import (
    PatternRuntimeRequest,
    PatternRuntimeService,
)
from src.agents.technical.subdomains.patterns.domain.pattern_detection_service import (
    detect_pattern_frame,
)


def test_pattern_runtime_exposes_atr_adaptive_thresholds() -> None:
    series = _build_price_series(base=100.0, drift=0.35, spread=1.0)
    runtime = PatternRuntimeService(timeframes=("1d",), min_points=30)

    result = runtime.compute(
        PatternRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": series},
        )
    )

    frame = result.pattern_pack.timeframes["1d"]
    assert result.degraded_reasons == []
    assert frame.confidence_scores["atr_value"] > 0.0
    assert (
        frame.confidence_scores["adaptive_bin_size"]
        > frame.confidence_scores["adaptive_breakout_buffer"]
        > 0.0
    )
    assert frame.confidence_scores["adaptive_proximity_tolerance"] > 0.0


def test_adaptive_thresholds_expand_with_higher_volatility() -> None:
    low_vol = detect_pattern_frame(
        _build_price_series(base=100.0, drift=0.25, spread=0.6),
        timeframe="1d",
    )
    high_vol = detect_pattern_frame(
        _build_price_series(base=100.0, drift=0.25, spread=3.0),
        timeframe="1d",
    )

    assert (
        high_vol.frame.confidence_scores["adaptive_bin_size"]
        > low_vol.frame.confidence_scores["adaptive_bin_size"]
    )
    assert (
        high_vol.frame.confidence_scores["adaptive_proximity_tolerance"]
        > low_vol.frame.confidence_scores["adaptive_proximity_tolerance"]
    )


def test_breakout_buffer_filters_marginal_high_vol_breakout() -> None:
    low_vol = detect_pattern_frame(
        _build_breakout_candidate_series(spread=0.4),
        timeframe="1d",
    )
    high_vol = detect_pattern_frame(
        _build_breakout_candidate_series(spread=4.0),
        timeframe="1d",
    )

    assert [flag.name for flag in low_vol.frame.breakouts] == ["BREAKOUT_UP"]
    assert high_vol.frame.breakouts == []


def _build_price_series(*, base: float, drift: float, spread: float) -> PriceSeries:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    open_series: dict[str, float] = {}
    high_series: dict[str, float] = {}
    low_series: dict[str, float] = {}
    close_series: dict[str, float] = {}
    volume_series: dict[str, float] = {}
    price_series: dict[str, float] = {}
    previous_close = base
    for idx in range(90):
        timestamp = (start + timedelta(days=idx)).isoformat()
        close = base + (idx * drift) + ((idx % 5) - 2) * 0.2
        open_price = previous_close + ((idx % 3) - 1) * 0.15
        high = max(open_price, close) + spread
        low = min(open_price, close) - spread
        open_series[timestamp] = round(open_price, 4)
        high_series[timestamp] = round(high, 4)
        low_series[timestamp] = round(low, 4)
        close_series[timestamp] = round(close, 4)
        price_series[timestamp] = round(close, 4)
        volume_series[timestamp] = float(1_000_000 + (idx * 5_000))
        previous_close = close
    return PriceSeries(
        timeframe="1d",
        start=min(price_series),
        end=max(price_series),
        price_series=price_series,
        volume_series=volume_series,
        open_series=open_series,
        high_series=high_series,
        low_series=low_series,
        close_series=close_series,
        timezone="UTC",
        metadata={},
    )


def _build_breakout_candidate_series(*, spread: float) -> PriceSeries:
    start = datetime(2025, 6, 1, tzinfo=UTC)
    closes = [100.0 + ((idx % 4) - 1.5) * 0.08 for idx in range(29)]
    closes.append(100.45)
    open_series: dict[str, float] = {}
    high_series: dict[str, float] = {}
    low_series: dict[str, float] = {}
    close_series: dict[str, float] = {}
    volume_series: dict[str, float] = {}
    price_series: dict[str, float] = {}
    previous_close = closes[0]
    for idx, close in enumerate(closes):
        timestamp = (start + timedelta(days=idx)).isoformat()
        open_price = previous_close + ((idx % 2) * 0.05)
        high = max(open_price, close) + spread
        low = min(open_price, close) - spread
        open_series[timestamp] = round(open_price, 4)
        high_series[timestamp] = round(high, 4)
        low_series[timestamp] = round(low, 4)
        close_series[timestamp] = round(close, 4)
        price_series[timestamp] = round(close, 4)
        volume_series[timestamp] = float(900_000 + idx * 1_000)
        previous_close = close
    return PriceSeries(
        timeframe="1d",
        start=min(price_series),
        end=max(price_series),
        price_series=price_series,
        volume_series=volume_series,
        open_series=open_series,
        high_series=high_series,
        low_series=low_series,
        close_series=close_series,
        timezone="UTC",
        metadata={},
    )
