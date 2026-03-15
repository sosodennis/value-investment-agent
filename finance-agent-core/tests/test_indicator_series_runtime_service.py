import pandas as pd

from src.agents.technical.subdomains.features.application.indicator_series_runtime_service import (
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
