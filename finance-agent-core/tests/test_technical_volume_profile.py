from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.agents.technical.application.use_cases.run_pattern_compute_use_case import (
    _pattern_pack_to_payload,
)
from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.subdomains.patterns import (
    PatternRuntimeRequest,
    PatternRuntimeService,
)
from src.agents.technical.subdomains.patterns.domain.pattern_detection_service import (
    detect_pattern_frame,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalPatternPackArtifactData,
)


def test_volume_profile_contract_payload_includes_vp_lite_fields() -> None:
    runtime = PatternRuntimeService(timeframes=("1d",), min_points=30)
    result = runtime.compute(
        PatternRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": _build_volume_profile_series(aligned=False)},
        )
    )

    payload = _pattern_pack_to_payload(result.pattern_pack, result.degraded_reasons)
    parsed = TechnicalPatternPackArtifactData.model_validate(payload)
    frame = parsed.timeframes["1d"]

    assert frame.volume_profile_levels
    assert frame.volume_profile_summary is not None
    assert frame.volume_profile_summary.poc is not None
    assert frame.volume_profile_summary.vah is not None
    assert frame.volume_profile_summary.val is not None
    assert frame.volume_profile_summary.profile_method == "daily_bar_approx"
    assert frame.volume_profile_summary.profile_fidelity == "low"
    assert frame.confluence_metadata is not None
    assert frame.confluence_metadata.volume_node_count == len(
        frame.volume_profile_levels
    )


def test_volume_profile_detects_high_volume_nodes() -> None:
    result = detect_pattern_frame(
        _build_volume_profile_series(aligned=False),
        timeframe="1d",
    )

    frame = result.frame
    assert result.degraded_reasons == []
    assert frame.volume_profile_levels
    dominant_node = frame.volume_profile_levels[0]
    assert dominant_node.label == "HVN"
    assert abs(dominant_node.price - 110.0) <= 1.5
    assert frame.volume_profile_summary is not None
    assert abs(frame.volume_profile_summary.poc - dominant_node.price) <= 1.5
    assert frame.volume_profile_summary.vah >= frame.volume_profile_summary.val


def test_volume_profile_marks_intraday_frames_with_higher_fidelity() -> None:
    result = detect_pattern_frame(
        _build_volume_profile_series(aligned=False, timeframe="1h"),
        timeframe="1h",
    )

    assert result.frame.volume_profile_summary is not None
    assert result.frame.volume_profile_summary.profile_method == "intraday_approx"
    assert result.frame.volume_profile_summary.profile_fidelity == "medium"


def test_volume_profile_confluence_score_increases_when_latest_price_aligns_with_node() -> (
    None
):
    aligned = detect_pattern_frame(
        _build_volume_profile_series(aligned=True),
        timeframe="1d",
    )
    dispersed = detect_pattern_frame(
        _build_volume_profile_series(aligned=False),
        timeframe="1d",
    )

    aligned_score = float(aligned.frame.confluence_metadata["confluence_score"])
    dispersed_score = float(dispersed.frame.confluence_metadata["confluence_score"])

    assert aligned_score > dispersed_score
    assert aligned.frame.confluence_metadata["confluence_state"] in {
        "moderate",
        "strong",
    }
    assert dispersed.frame.confluence_metadata["confluence_state"] in {"none", "weak"}


def _build_volume_profile_series(
    *, aligned: bool, timeframe: str = "1d"
) -> PriceSeries:
    start = datetime(2025, 7, 1, tzinfo=UTC)
    open_series: dict[str, float] = {}
    high_series: dict[str, float] = {}
    low_series: dict[str, float] = {}
    close_series: dict[str, float] = {}
    volume_series: dict[str, float] = {}
    price_series: dict[str, float] = {}
    previous_close = 103.0
    for idx in range(60):
        timestamp = (start + timedelta(days=idx)).isoformat()
        if idx < 45:
            close = 110.0 + ((idx % 5) - 2) * 0.18
            volume = 2_200_000 + idx * 5_000
        elif aligned:
            close = 110.4 + ((idx - 45) % 4) * 0.08
            volume = 3_000_000 + idx * 12_000
        else:
            close = 116.0 + idx * 0.08
            volume = 650_000 + idx * 2_000
        open_price = previous_close + ((idx % 3) - 1) * 0.1
        high = max(open_price, close) + 0.9
        low = min(open_price, close) - 0.75
        open_series[timestamp] = round(open_price, 4)
        high_series[timestamp] = round(high, 4)
        low_series[timestamp] = round(low, 4)
        close_series[timestamp] = round(close, 4)
        price_series[timestamp] = round(close, 4)
        volume_series[timestamp] = float(volume)
        previous_close = close
    return PriceSeries(
        timeframe=timeframe,
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
