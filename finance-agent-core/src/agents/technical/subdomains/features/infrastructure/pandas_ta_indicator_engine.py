from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

from src.agents.technical.domain.shared import IndicatorSnapshot
from src.agents.technical.subdomains.features.application.ports import (
    IIndicatorEngine,
    IndicatorEngineAvailability,
    IndicatorEngineResult,
)
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)

try:
    import pandas_ta as ta
except Exception as exc:  # pragma: no cover - depends on optional dependency
    ta = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = None


@dataclass(frozen=True)
class PandasTaIndicatorEngine(IIndicatorEngine):
    def availability(self) -> IndicatorEngineAvailability:
        if ta is None:
            return IndicatorEngineAvailability(False, reason="PANDAS_TA_MISSING")
        return IndicatorEngineAvailability(True)

    def compute_classic_indicators(
        self,
        *,
        price_series: pd.Series,
        volume_series: pd.Series,
        latest_price: float | None,
    ) -> IndicatorEngineResult:
        if ta is None:
            log_event(
                logger,
                event="technical_indicator_engine_missing",
                message="pandas-ta dependency missing",
                level=logging.WARNING,
                error_code="TECHNICAL_INDICATOR_ENGINE_MISSING",
                fields={"error": _IMPORT_ERROR or "missing_dependency"},
            )
            return IndicatorEngineResult(
                indicators={},
                degraded_reasons=["PANDAS_TA_MISSING"],
            )

        try:
            return _compute_classic_indicators(
                price_series=price_series,
                volume_series=volume_series,
                latest_price=latest_price,
            )
        except Exception as exc:
            log_event(
                logger,
                event="technical_indicator_engine_failed",
                message="pandas-ta indicator computation failed",
                level=logging.ERROR,
                error_code="TECHNICAL_INDICATOR_ENGINE_FAILED",
                fields={"error": bounded_text(exc)},
            )
            return IndicatorEngineResult(
                indicators={},
                degraded_reasons=["INDICATOR_ENGINE_FAILED"],
            )


def _compute_classic_indicators(
    *,
    price_series: pd.Series,
    volume_series: pd.Series,
    latest_price: float | None,
) -> IndicatorEngineResult:
    indicators: dict[str, IndicatorSnapshot] = {}
    degraded: list[str] = []

    price_series = _clean_series(price_series)
    volume_series = _clean_series(volume_series)

    if price_series.empty:
        degraded.append("PRICE_EMPTY")
        return IndicatorEngineResult(indicators=indicators, degraded_reasons=degraded)

    sma_20 = ta.sma(price_series, length=20)
    sma_val = _latest_value(sma_20)
    indicators["SMA_20"] = _snapshot(
        "SMA_20", sma_val, state=_compare_state(latest_price, sma_val)
    )

    ema_20 = ta.ema(price_series, length=20)
    ema_val = _latest_value(ema_20)
    indicators["EMA_20"] = _snapshot(
        "EMA_20", ema_val, state=_compare_state(latest_price, ema_val)
    )

    rsi = ta.rsi(price_series, length=14)
    rsi_val = _latest_value(rsi)
    indicators["RSI_14"] = _snapshot("RSI_14", rsi_val, state=_momentum_state(rsi_val))

    macd_df = ta.macd(price_series, fast=12, slow=26, signal=9)
    macd_val = _latest_value(_select_macd_series(macd_df, "MACD_"))
    signal_val = _latest_value(_select_macd_series(macd_df, "MACDs_"))
    hist_val = _latest_value(_select_macd_series(macd_df, "MACDh_"))
    indicators["MACD"] = _snapshot(
        "MACD",
        macd_val,
        state=_macd_state(macd_val, signal_val),
        metadata={
            "signal": _safe_float(signal_val),
            "hist": _safe_float(hist_val),
        },
    )

    if volume_series.empty:
        indicators["VWAP"] = _snapshot(
            "VWAP", None, state="UNAVAILABLE", metadata={"reason": "missing_volume"}
        )
        indicators["MFI_14"] = _snapshot(
            "MFI_14",
            None,
            state="UNAVAILABLE",
            metadata={"reason": "missing_volume"},
        )
    else:
        vwap_series = ta.vwap(
            high=price_series,
            low=price_series,
            close=price_series,
            volume=volume_series,
        )
        vwap_val = _latest_value(vwap_series)
        indicators["VWAP"] = _snapshot(
            "VWAP", vwap_val, state=_compare_state(latest_price, vwap_val)
        )

        mfi_series = ta.mfi(
            high=price_series,
            low=price_series,
            close=price_series,
            volume=volume_series,
            length=14,
        )
        mfi_val = _latest_value(mfi_series)
        indicators["MFI_14"] = _snapshot(
            "MFI_14", mfi_val, state=_momentum_state(mfi_val)
        )

    indicators["ATR_14"] = _snapshot(
        "ATR_14",
        None,
        state="UNAVAILABLE",
        metadata={"reason": "missing_high_low"},
    )

    return IndicatorEngineResult(indicators=indicators, degraded_reasons=degraded)


def _select_macd_series(df: pd.DataFrame | None, prefix: str) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for column in df.columns:
        if str(column).startswith(prefix):
            return df[column]
    return None


def _clean_series(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    cleaned = series.copy()
    cleaned = pd.to_numeric(cleaned, errors="coerce")
    cleaned = cleaned.replace([math.inf, -math.inf], math.nan)
    return cleaned.dropna()


def _safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _snapshot(
    name: str,
    value: float | int | None,
    *,
    state: str | None = None,
    metadata: dict[str, float | int | str | bool | None] | None = None,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        name=name,
        value=_safe_float(value),
        state=state,
        metadata=metadata or {},
    )


def _latest_value(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    return _safe_float(series.iloc[-1])


def _compare_state(latest_price: float | None, reference: float | None) -> str | None:
    if latest_price is None or reference is None:
        return "UNAVAILABLE"
    if latest_price > reference:
        return "ABOVE"
    if latest_price < reference:
        return "BELOW"
    return "NEUTRAL"


def _momentum_state(value: float | None) -> str | None:
    if value is None:
        return "UNAVAILABLE"
    if value >= 70.0:
        return "OVERBOUGHT"
    if value <= 30.0:
        return "OVERSOLD"
    return "NEUTRAL"


def _macd_state(macd_val: float | None, signal_val: float | None) -> str | None:
    if macd_val is None or signal_val is None:
        return "UNAVAILABLE"
    if macd_val > signal_val:
        return "BULLISH"
    if macd_val < signal_val:
        return "BEARISH"
    return "NEUTRAL"
