import pandas as pd

from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.subdomains.features.application.indicator_series_runtime_service import (
    IndicatorSeriesRuntimeRequest,
    IndicatorSeriesRuntimeService,
    _downsample_index,
)


def test_downsample_index_noop_when_under_limit() -> None:
    index = pd.date_range("2026-01-01", periods=10, freq="D")
    sampled, step = _downsample_index(index, 20)

    assert step == 1
    assert list(sampled) == list(index)


def test_downsample_index_limits_and_preserves_last() -> None:
    index = pd.date_range("2026-01-01", periods=10, freq="D")
    sampled, step = _downsample_index(index, 3)

    assert step == 4
    assert len(sampled) <= 3
    assert sampled[0] == index[0]
    assert sampled[-1] == index[-1]
    assert sampled.is_monotonic_increasing


def test_indicator_series_runtime_builds_typed_frame_metadata() -> None:
    service = IndicatorSeriesRuntimeService(max_points=10, min_quant_points=300)
    index = pd.date_range("2026-01-01", periods=25, freq="D", tz="UTC")
    close_values = [float(100 + i) for i in range(25)]
    series = PriceSeries(
        timeframe="1d",
        start=index[0].isoformat(),
        end=index[-1].isoformat(),
        price_series={
            ts.isoformat(): value for ts, value in zip(index, close_values, strict=True)
        },
        volume_series={ts.isoformat(): float(1000 + i) for i, ts in enumerate(index)},
        close_series={
            ts.isoformat(): value for ts, value in zip(index, close_values, strict=True)
        },
        high_series={
            ts.isoformat(): value + 1.0
            for ts, value in zip(index, close_values, strict=True)
        },
        low_series={
            ts.isoformat(): value - 1.0
            for ts, value in zip(index, close_values, strict=True)
        },
        timezone="UTC",
    )

    result = service.compute(
        IndicatorSeriesRuntimeRequest(
            ticker="AAPL",
            as_of="2026-02-12T00:00:00Z",
            series_by_timeframe={"1d": series},
        )
    )

    metadata = result.timeframes["1d"].metadata
    assert metadata.source_points == 25
    assert metadata.max_points == 10
    assert metadata.downsample_step == 3
    assert metadata.source_price_basis == "close"
    assert metadata.sample_readiness == "partial"
    assert metadata.fidelity == "medium"
    assert metadata.quality_flags == ("DOWNSAMPLED", "QUANT_SKIPPED")
