from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.agents.technical.domain.shared import PriceSeries, TimeframeCode
from src.agents.technical.subdomains.features.domain import (
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    compute_adx,
    compute_atr,
    compute_atrp,
    compute_bollinger,
    compute_bollinger_bandwidth,
    compute_ema,
    compute_macd,
    compute_mfi,
    compute_rsi,
    compute_sma,
    compute_vwap,
    supports_session_vwap_timeframe,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


@dataclass(frozen=True)
class IndicatorSeriesRuntimeRequest:
    ticker: str
    as_of: str
    series_by_timeframe: dict[TimeframeCode, PriceSeries]


@dataclass(frozen=True)
class IndicatorSeriesFrameResult:
    timeframe: TimeframeCode
    start: str
    end: str
    series: dict[str, dict[str, float | None]]
    timezone: str | None = None
    metadata: IndicatorSeriesFrameMetadata | dict[str, object] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class IndicatorSeriesFrameMetadata:
    source_points: int
    max_points: int
    downsample_step: int
    source_timeframe: str
    source_price_basis: str
    effective_sample_count: int
    minimum_sample_count: int
    sample_readiness: str
    fidelity: str
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorSeriesRuntimeResult:
    ticker: str
    as_of: str
    timeframes: dict[TimeframeCode, IndicatorSeriesFrameResult]
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IndicatorSeriesRuntimeService:
    max_points: int = 1500
    min_quant_points: int = 300
    quant_timeframes: tuple[TimeframeCode, ...] = ("1d",)

    def compute(
        self, request: IndicatorSeriesRuntimeRequest
    ) -> IndicatorSeriesRuntimeResult:
        frames: dict[TimeframeCode, IndicatorSeriesFrameResult] = {}
        degraded: list[str] = []

        for timeframe, series in request.series_by_timeframe.items():
            frame, frame_degraded = _compute_frame(
                timeframe=timeframe,
                series=series,
                max_points=self.max_points,
                min_quant_points=self.min_quant_points,
                include_quant=timeframe in self.quant_timeframes,
            )
            frames[timeframe] = frame
            degraded.extend([f"{timeframe}_{reason}" for reason in frame_degraded])

        return IndicatorSeriesRuntimeResult(
            ticker=request.ticker,
            as_of=request.as_of,
            timeframes=frames,
            degraded_reasons=degraded,
        )


def _compute_frame(
    *,
    timeframe: TimeframeCode,
    series: PriceSeries,
    max_points: int,
    min_quant_points: int,
    include_quant: bool,
) -> tuple[IndicatorSeriesFrameResult, list[str]]:
    degraded: list[str] = []
    close_payload = series.close_series or series.price_series
    close_series = _build_series(close_payload)
    if close_series.empty:
        degraded.append("PRICE_EMPTY")
        return (
            IndicatorSeriesFrameResult(
                timeframe=timeframe,
                start=series.start,
                end=series.end,
                series={},
                timezone=series.timezone,
                metadata=_frame_metadata(
                    timeframe=timeframe,
                    source_points=0,
                    max_points=max_points,
                    step=1,
                    min_quant_points=min_quant_points,
                    price_basis="close" if series.close_series else "price",
                    quality_flags=("PRICE_EMPTY",),
                ),
            ),
            degraded,
        )

    close_series = close_series.sort_index()
    base_index = close_series.index

    volume_series = _build_series(series.volume_series).reindex(base_index)
    high_series = _build_series(series.high_series).reindex(base_index)
    low_series = _build_series(series.low_series).reindex(base_index)

    indicator_series: dict[str, pd.Series] = {}
    indicator_series["SMA_20"] = compute_sma(close_series, window=20)
    indicator_series["EMA_20"] = compute_ema(close_series, window=20)
    indicator_series["RSI_14"] = compute_rsi(close_series, window=14)

    macd_line, macd_signal, macd_hist = compute_macd(close_series)
    indicator_series["MACD"] = macd_line
    indicator_series["MACD_SIGNAL"] = macd_signal
    indicator_series["MACD_HIST"] = macd_hist

    bb_upper, bb_middle, bb_lower = compute_bollinger(
        close_series, window=20, num_std=2.0
    )
    indicator_series["BB_UPPER"] = bb_upper
    indicator_series["BB_MIDDLE"] = bb_middle
    indicator_series["BB_LOWER"] = bb_lower

    if (
        supports_session_vwap_timeframe(timeframe)
        and _series_has_data(volume_series)
        and _series_has_data(high_series)
        and _series_has_data(low_series)
    ):
        indicator_series["VWAP"] = compute_vwap(
            high_series,
            low_series,
            close_series,
            volume_series,
        )
        indicator_series["MFI_14"] = compute_mfi(close_series, volume_series, window=14)
    else:
        indicator_series["VWAP"] = _empty_series_like(close_series)
        if _series_has_data(volume_series):
            indicator_series["MFI_14"] = compute_mfi(
                close_series, volume_series, window=14
            )
        else:
            degraded.append("VOLUME_EMPTY")
            indicator_series["MFI_14"] = _empty_series_like(close_series)

    if _series_has_data(high_series) and _series_has_data(low_series):
        atr_series = compute_atr(high_series, low_series, close_series, window=14)
        if atr_series is None:
            indicator_series["ATR_14"] = _empty_series_like(close_series)
            indicator_series["ADX_14"] = _empty_series_like(close_series)
            indicator_series["ATRP_14"] = _empty_series_like(close_series)
        else:
            indicator_series["ATR_14"] = atr_series
            adx_series = compute_adx(high_series, low_series, close_series, window=14)
            atrp_series = compute_atrp(high_series, low_series, close_series, window=14)
            indicator_series["ADX_14"] = (
                adx_series
                if adx_series is not None
                else _empty_series_like(close_series)
            )
            indicator_series["ATRP_14"] = (
                atrp_series
                if atrp_series is not None
                else _empty_series_like(close_series)
            )
    else:
        degraded.append("OHLC_MISSING")
        indicator_series["ATR_14"] = _empty_series_like(close_series)
        indicator_series["ADX_14"] = _empty_series_like(close_series)
        indicator_series["ATRP_14"] = _empty_series_like(close_series)

    indicator_series["BB_BANDWIDTH_20"] = compute_bollinger_bandwidth(
        close_series,
        window=20,
        num_std=2.0,
    )

    if include_quant and _series_has_min_points(close_series, min_quant_points):
        try:
            fd_series, _, _, _, _ = calculate_rolling_fracdiff(close_series)
            indicator_series["FD"] = fd_series
            indicator_series["FD_ZSCORE"] = calculate_rolling_z_score(fd_series)
        except Exception as exc:
            log_event(
                logger,
                event="technical_indicator_series_quant_failed",
                message="technical indicator series quant computation failed",
                error_code="TECHNICAL_INDICATOR_SERIES_QUANT_FAILED",
                fields={"timeframe": timeframe, "error": str(exc)},
            )
            degraded.append("QUANT_FAILED")
    else:
        degraded.append("QUANT_SKIPPED")

    sampled_index, step = _downsample_index(base_index, max_points)
    series_payload = {
        name: _series_to_json(series.reindex(base_index).loc[sampled_index])
        for name, series in indicator_series.items()
    }

    metadata = _frame_metadata(
        timeframe=timeframe,
        source_points=len(base_index),
        max_points=max_points,
        step=step,
        min_quant_points=min_quant_points,
        price_basis="close" if series.close_series else "price",
        quality_flags=tuple(_frame_quality_flags(step=step, degraded=degraded)),
    )

    return (
        IndicatorSeriesFrameResult(
            timeframe=timeframe,
            start=series.start,
            end=series.end,
            series=series_payload,
            timezone=series.timezone,
            metadata=metadata,
        ),
        degraded,
    )


def _frame_metadata(
    *,
    timeframe: TimeframeCode,
    source_points: int,
    max_points: int,
    step: int,
    min_quant_points: int,
    price_basis: str,
    quality_flags: tuple[str, ...],
) -> IndicatorSeriesFrameMetadata:
    return IndicatorSeriesFrameMetadata(
        source_points=source_points,
        max_points=max_points,
        downsample_step=step,
        source_timeframe=timeframe,
        source_price_basis=price_basis,
        effective_sample_count=source_points,
        minimum_sample_count=min_quant_points,
        sample_readiness=_sample_readiness(
            source_points=source_points,
            min_quant_points=min_quant_points,
        ),
        fidelity=_frame_fidelity(source_points=source_points, step=step),
        quality_flags=quality_flags,
    )


def _frame_quality_flags(*, step: int, degraded: list[str]) -> list[str]:
    flags: list[str] = []
    if step > 1:
        flags.append("DOWNSAMPLED")
    for reason in degraded:
        if reason not in flags:
            flags.append(reason)
    return flags


def _sample_readiness(*, source_points: int, min_quant_points: int) -> str:
    if source_points <= 0:
        return "empty"
    if source_points < min_quant_points:
        return "partial"
    return "ready"


def _frame_fidelity(*, source_points: int, step: int) -> str:
    if source_points <= 0:
        return "low"
    if step > 1:
        return "medium"
    return "high"


def _downsample_index(index: pd.Index, max_points: int) -> tuple[pd.Index, int]:
    length = len(index)
    if length == 0 or max_points <= 0 or length <= max_points:
        return index, 1

    step = math.ceil(length / max_points)
    positions = list(range(0, length, step))
    if positions[-1] != length - 1:
        positions[-1] = length - 1

    return index.take(positions), step


def _build_series(payload: dict[str, float | None] | None) -> pd.Series:
    if not payload:
        return pd.Series(dtype=float)
    series = pd.Series(payload)
    series = pd.to_numeric(series, errors="coerce")
    series = series.replace([math.inf, -math.inf], math.nan)
    return series


def _series_has_data(series: pd.Series | None) -> bool:
    if series is None or series.empty:
        return False
    return not series.dropna().empty


def _series_has_min_points(series: pd.Series, min_points: int) -> bool:
    if series.empty:
        return False
    return len(series.dropna()) >= min_points


def _empty_series_like(series: pd.Series) -> pd.Series:
    return pd.Series([math.nan] * len(series), index=series.index)


def _series_to_json(series: pd.Series) -> dict[str, float | None]:
    series = series.astype(object).where(pd.notnull(series), None)
    payload: dict[str, float | None] = {}
    for idx, raw in series.items():
        key = idx.isoformat() if isinstance(idx, pd.Timestamp) else str(idx)
        payload[key] = _safe_float(raw)
    return payload


def _safe_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
