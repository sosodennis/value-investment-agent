from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.agents.technical.application.use_cases.run_fusion_compute_use_case import (
    _resolve_confidence_eligibility,
    _resolve_effective_signal_strength,
)
from src.agents.technical.domain.shared import (
    FeatureFrame,
    FeaturePack,
    IndicatorSnapshot,
    PatternFlag,
    PatternFrame,
    PatternPack,
    PriceSeries,
)
from src.agents.technical.subdomains.features import (
    FeatureRuntimeRequest,
    FeatureRuntimeService,
    IndicatorSeriesRuntimeRequest,
    IndicatorSeriesRuntimeService,
)
from src.agents.technical.subdomains.regime.application.regime_runtime_service import (
    RegimeRuntimeRequest,
    RegimeRuntimeService,
)
from src.agents.technical.subdomains.regime.contracts import RegimeFrame, RegimePack
from src.agents.technical.subdomains.signal_fusion import (
    FusionRuntimeRequest,
    FusionRuntimeService,
)


def test_regime_runtime_classifies_bull_trend_from_ohlc_series() -> None:
    runtime = RegimeRuntimeService(timeframes=("1d",))

    result = runtime.compute(
        RegimeRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": _build_price_series(base=100.0, drift=2.0)},
        )
    )

    frame = result.regime_pack.timeframes["1d"]
    assert result.degraded_reasons == []
    assert frame.regime == "BULL_TREND"
    assert frame.directional_bias == "bullish"
    assert result.regime_pack.regime_summary["dominant_regime"] == "BULL_TREND"


def test_feature_runtime_exposes_canonical_regime_snapshots() -> None:
    runtime = FeatureRuntimeService(quant_timeframes=())

    result = runtime.compute(
        FeatureRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": _build_price_series(base=100.0, drift=1.4)},
        )
    )

    frame = result.feature_pack.timeframes["1d"]
    assert frame.classic_indicators["ATR_14"].value is not None
    assert frame.classic_indicators["ATRP_14"].value is not None
    assert frame.classic_indicators["ADX_14"].value is not None
    assert frame.classic_indicators["BB_BANDWIDTH_20"].value is not None


def test_feature_runtime_marks_non_intraday_vwap_unavailable() -> None:
    runtime = FeatureRuntimeService(quant_timeframes=())

    result = runtime.compute(
        FeatureRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": _build_price_series(base=100.0, drift=1.4)},
        )
    )

    vwap = result.feature_pack.timeframes["1d"].classic_indicators["VWAP"]
    assert vwap.value is None
    assert vwap.state == "UNAVAILABLE"
    assert vwap.metadata["reason"] == "requires_intraday_session_bars"


def test_feature_runtime_computes_volatility_regime_quant_features() -> None:
    runtime = FeatureRuntimeService()

    result = runtime.compute(
        FeatureRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={
                "1d": _build_price_series(base=100.0, drift=0.45, periods=320)
            },
        )
    )

    frame = result.feature_pack.timeframes["1d"]
    assert frame.quant_features["VOL_REALIZED_20"].value is not None
    assert frame.quant_features["VOL_DOWNSIDE_20"].value is not None
    assert frame.quant_features["VOL_PERCENTILE_252"].value is not None
    assert frame.quant_features["VOL_PERCENTILE_252"].state in {
        "COMPRESSED",
        "NORMAL",
        "ELEVATED",
    }
    assert frame.quant_features["VOL_REALIZED_20"].metadata["window"] == 20
    assert (
        frame.quant_features["VOL_REALIZED_20"].metadata["annualization_factor"] == 252
    )
    assert frame.quant_features["VOL_PERCENTILE_252"].quality is not None
    assert frame.quant_features["VOL_PERCENTILE_252"].quality.warmup_status == "READY"


def test_feature_runtime_computes_liquidity_proxy_quant_features() -> None:
    runtime = FeatureRuntimeService()

    result = runtime.compute(
        FeatureRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={
                "1d": _build_price_series(base=100.0, drift=0.45, periods=320)
            },
        )
    )

    frame = result.feature_pack.timeframes["1d"]
    assert frame.quant_features["DOLLAR_VOLUME_20"].value is not None
    assert frame.quant_features["AMIHUD_ILLIQUIDITY_20"].value is not None
    assert frame.quant_features["DOLLAR_VOLUME_PERCENTILE_252"].value is not None
    assert frame.quant_features["DOLLAR_VOLUME_PERCENTILE_252"].state in {
        "THIN",
        "NORMAL",
        "LIQUID",
    }
    assert frame.quant_features["DOLLAR_VOLUME_20"].metadata["window"] == 20
    assert frame.quant_features["AMIHUD_ILLIQUIDITY_20"].metadata["scale"] == 1_000_000
    assert frame.quant_features["DOLLAR_VOLUME_PERCENTILE_252"].quality is not None
    assert (
        frame.quant_features["DOLLAR_VOLUME_PERCENTILE_252"].quality.warmup_status
        == "READY"
    )


def test_indicator_series_runtime_exposes_canonical_regime_series() -> None:
    runtime = IndicatorSeriesRuntimeService(quant_timeframes=())

    result = runtime.compute(
        IndicatorSeriesRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": _build_price_series(base=100.0, drift=1.1)},
        )
    )

    frame = result.timeframes["1d"]
    assert _latest_series_value(frame.series["ATR_14"]) is not None
    assert _latest_series_value(frame.series["ATRP_14"]) is not None
    assert _latest_series_value(frame.series["ADX_14"]) is not None
    assert _latest_series_value(frame.series["BB_BANDWIDTH_20"]) is not None


def test_indicator_series_runtime_omits_non_intraday_vwap_series() -> None:
    runtime = IndicatorSeriesRuntimeService(quant_timeframes=())

    result = runtime.compute(
        IndicatorSeriesRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": _build_price_series(base=100.0, drift=1.1)},
        )
    )

    frame = result.timeframes["1d"]
    assert _latest_series_value(frame.series["VWAP"]) is None


def test_feature_runtime_computes_session_vwap_for_intraday_series() -> None:
    runtime = FeatureRuntimeService(quant_timeframes=())

    result = runtime.compute(
        FeatureRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1h": _build_intraday_price_series(base=100.0)},
        )
    )

    vwap = result.feature_pack.timeframes["1h"].classic_indicators["VWAP"]
    assert vwap.value is not None
    assert vwap.state in {"ABOVE", "BELOW", "AT"}


def test_regime_runtime_prefers_canonical_inputs_without_ohlc_recompute() -> None:
    runtime = RegimeRuntimeService(timeframes=("1d",))
    raw_series = _build_price_series(base=100.0, drift=1.8)
    canonical_series = PriceSeries(
        timeframe=raw_series.timeframe,
        start=raw_series.start,
        end=raw_series.end,
        price_series=raw_series.price_series,
        volume_series=raw_series.volume_series,
        open_series=raw_series.open_series,
        high_series=None,
        low_series=None,
        close_series=raw_series.close_series,
        timezone=raw_series.timezone,
        metadata={
            "regime_input_atr_14": 1.84,
            "regime_input_atrp_14": 0.0184,
            "regime_input_adx_14": 33.5,
            "regime_input_bb_bandwidth_20": 0.062,
        },
    )

    result = runtime.compute(
        RegimeRuntimeRequest(
            ticker="AAPL",
            as_of="2026-03-17T00:00:00Z",
            series_by_timeframe={"1d": canonical_series},
        )
    )

    frame = result.regime_pack.timeframes["1d"]
    assert result.degraded_reasons == []
    assert frame.adx == 33.5
    assert frame.atr_value == 1.84
    assert frame.atrp_value == 0.0184
    assert frame.bollinger_bandwidth == 0.062


def test_fusion_runtime_uses_bull_trend_regime_to_amplify_aligned_scores() -> None:
    service = FusionRuntimeService()
    request = _build_fusion_request(
        regime_frame=RegimeFrame(
            timeframe="1d",
            regime="BULL_TREND",
            confidence=0.82,
            directional_bias="bullish",
            evidence=("bias=bullish", "adx=32.4"),
            metadata={"bias_score": 3},
        )
    )

    with_regime = service.compute(request)
    without_regime = service.compute(
        FusionRuntimeRequest(
            ticker=request.ticker,
            as_of=request.as_of,
            feature_pack=request.feature_pack,
            pattern_pack=request.pattern_pack,
        )
    )

    assert with_regime.scorecard is not None
    assert without_regime.scorecard is not None
    frame = with_regime.scorecard.timeframes["1d"]
    assert frame.total_score > frame.base_total_score
    assert with_regime.scorecard.overall_score > without_regime.scorecard.overall_score
    assert (
        with_regime.fusion_signal.diagnostics.confluence_matrix["1d"]["regime"]
        == "BULL_TREND"
    )
    assert frame.regime_weight_multiplier is not None
    assert frame.regime_weight_multiplier > 1.0


def test_fusion_runtime_dampens_signals_in_high_vol_chop_regime() -> None:
    service = FusionRuntimeService()
    result = service.compute(
        _build_fusion_request(
            regime_frame=RegimeFrame(
                timeframe="1d",
                regime="HIGH_VOL_CHOP",
                confidence=0.73,
                directional_bias="neutral",
                evidence=("atrp=0.0410", "bb_bw=0.1800"),
                metadata={"bias_score": 0},
            )
        )
    )

    assert result.scorecard is not None
    frame = result.scorecard.timeframes["1d"]
    assert frame.total_score < frame.base_total_score
    assert result.fusion_signal.risk_level == "medium"
    assert "volatility_penalty" in frame.regime_notes
    assert any(
        "HIGH_VOL_CHOP" in reason for reason in result.scorecard.conflict_reasons
    )


def test_effective_signal_strength_applies_penalties() -> None:
    effective = _resolve_effective_signal_strength(
        raw_strength=0.99,
        degraded_reasons=["1h_UNAVAILABLE", "1wk_QUANT_SKIPPED"],
        conflict_reasons=["1wk:REGIME_HIGH_VOL_CHOP_DAMPENS_SIGNALS"],
        calibration_applied=False,
    )

    assert effective == 0.78


def test_confidence_eligibility_marks_neutral_uncalibrated_path_ineligible() -> None:
    eligibility = _resolve_confidence_eligibility(
        direction="NEUTRAL_CONSOLIDATION",
        calibration_applied=False,
        degraded_reasons=["1h_UNAVAILABLE"],
        conflict_reasons=[],
    )

    assert eligibility["eligible"] is False
    assert eligibility["normalized_direction"] == "neutral"
    assert eligibility["reason_codes"] == [
        "NEUTRAL_DIRECTION",
        "CALIBRATION_NOT_APPLIED",
        "DEGRADED_INPUTS_PRESENT",
    ]


def _build_fusion_request(*, regime_frame: RegimeFrame) -> FusionRuntimeRequest:
    feature_pack = FeaturePack(
        ticker="AAPL",
        as_of="2026-03-17T00:00:00Z",
        timeframes={
            "1d": FeatureFrame(
                classic_indicators={
                    "EMA_20": IndicatorSnapshot(
                        name="EMA_20",
                        value=111.0,
                        state="ABOVE",
                    ),
                    "MACD": IndicatorSnapshot(
                        name="MACD",
                        value=1.4,
                        state="BULLISH",
                    ),
                    "RSI_14": IndicatorSnapshot(
                        name="RSI_14",
                        value=48.0,
                        state="NEUTRAL",
                    ),
                },
                quant_features={
                    "FD_Z_SCORE": IndicatorSnapshot(
                        name="FD_Z_SCORE",
                        value=1.6,
                        state="DEVIATING",
                    ),
                    "FD_OBV_Z": IndicatorSnapshot(
                        name="FD_OBV_Z",
                        value=0.9,
                        state="ACCUMULATION_ANOMALY",
                    ),
                    "FD_STAT_STRENGTH": IndicatorSnapshot(
                        name="FD_STAT_STRENGTH",
                        value=70.0,
                        state="CONFIRMED",
                    ),
                },
            )
        },
    )
    pattern_pack = PatternPack(
        ticker="AAPL",
        as_of="2026-03-17T00:00:00Z",
        timeframes={
            "1d": PatternFrame(
                breakouts=[PatternFlag(name="BREAKOUT_UP", confidence=0.81)],
                trendlines=[PatternFlag(name="UPTREND", confidence=0.74)],
            )
        },
    )
    regime_pack = RegimePack(
        ticker="AAPL",
        as_of="2026-03-17T00:00:00Z",
        timeframes={"1d": regime_frame},
        regime_summary={"dominant_regime": regime_frame.regime, "timeframe_count": 1},
    )
    return FusionRuntimeRequest(
        ticker="AAPL",
        as_of="2026-03-17T00:00:00Z",
        feature_pack=feature_pack,
        pattern_pack=pattern_pack,
        regime_pack=regime_pack,
    )


def _build_price_series(*, base: float, drift: float, periods: int = 90) -> PriceSeries:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    open_series: dict[str, float] = {}
    high_series: dict[str, float] = {}
    low_series: dict[str, float] = {}
    close_series: dict[str, float] = {}
    volume_series: dict[str, float] = {}
    price_series: dict[str, float] = {}
    previous_close = base
    for idx in range(periods):
        timestamp = (start + timedelta(days=idx)).isoformat()
        close = base + (idx * drift) + ((idx % 4) - 1.5) * 0.18
        open_price = previous_close + ((idx % 3) - 1) * 0.12
        high = max(open_price, close) + 1.1
        low = min(open_price, close) - 0.9
        open_series[timestamp] = round(open_price, 4)
        high_series[timestamp] = round(high, 4)
        low_series[timestamp] = round(low, 4)
        close_series[timestamp] = round(close, 4)
        price_series[timestamp] = round(close, 4)
        volume_series[timestamp] = float(1_200_000 + idx * 7_500)
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


def _latest_series_value(series: dict[str, float | None]) -> float | None:
    values = [value for value in series.values() if value is not None]
    return values[-1] if values else None


def _build_intraday_price_series(*, base: float) -> PriceSeries:
    start = datetime(2026, 3, 16, 14, 30, tzinfo=UTC)
    open_series: dict[str, float] = {}
    high_series: dict[str, float] = {}
    low_series: dict[str, float] = {}
    close_series: dict[str, float] = {}
    volume_series: dict[str, float] = {}
    price_series: dict[str, float] = {}
    previous_close = base
    for idx in range(14):
        if idx < 7:
            day_start = start
            day_offset = idx
        else:
            day_start = start + timedelta(days=1)
            day_offset = idx - 7
        timestamp = (day_start + timedelta(hours=day_offset)).isoformat()
        close = base + (idx * 0.7) + ((idx % 3) - 1) * 0.2
        open_price = previous_close + ((idx % 2) - 0.5) * 0.3
        high = max(open_price, close) + 0.8
        low = min(open_price, close) - 0.6
        open_series[timestamp] = round(open_price, 4)
        high_series[timestamp] = round(high, 4)
        low_series[timestamp] = round(low, 4)
        close_series[timestamp] = round(close, 4)
        price_series[timestamp] = round(close, 4)
        volume_series[timestamp] = float(250_000 + idx * 8_000)
        previous_close = close
    return PriceSeries(
        timeframe="1h",
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
