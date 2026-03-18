from __future__ import annotations

from src.agents.technical.application.ports import TechnicalSignalExplainerInput
from src.agents.technical.interface.indicator_explainer_catalog import (
    iter_indicator_explainer_entries,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalFeatureIndicatorData,
    TechnicalFeaturePackArtifactData,
)

_PREFERRED_TIMEFRAMES = ("1d", "1wk", "1h")
_MAX_EXPLAINERS = 3


def build_signal_explainer_context(
    feature_pack: TechnicalFeaturePackArtifactData | None,
) -> tuple[TechnicalSignalExplainerInput, ...]:
    if feature_pack is None or not feature_pack.timeframes:
        return ()

    timeframe = _select_preferred_timeframe(feature_pack)
    if timeframe is None:
        return ()

    candidates: list[TechnicalSignalExplainerInput] = []
    for entry in iter_indicator_explainer_entries():
        indicator = _resolve_indicator(feature_pack, timeframe, entry.signal)
        if indicator is None or indicator.value is None:
            continue
        candidates.append(
            TechnicalSignalExplainerInput(
                signal=entry.signal,
                plain_name=entry.plain_name,
                value_text=_format_value_text(entry.signal, indicator.value),
                timeframe=timeframe,
                state=_normalize_state(indicator.state),
                what_it_measures=entry.what_it_measures,
                current_reading_hint=_build_current_reading_hint(
                    signal=entry.signal,
                    value=indicator.value,
                    state=indicator.state,
                ),
                why_it_matters=entry.why_it_matters,
            )
        )
    return tuple(candidates[:_MAX_EXPLAINERS])


def _select_preferred_timeframe(
    feature_pack: TechnicalFeaturePackArtifactData,
) -> str | None:
    for timeframe in _PREFERRED_TIMEFRAMES:
        if timeframe in feature_pack.timeframes:
            return timeframe
    return next(iter(feature_pack.timeframes), None)


def _resolve_indicator(
    feature_pack: TechnicalFeaturePackArtifactData,
    timeframe: str,
    signal: str,
) -> TechnicalFeatureIndicatorData | None:
    frame = feature_pack.timeframes.get(timeframe)
    if frame is None:
        return None
    if signal in frame.classic_indicators:
        return frame.classic_indicators[signal]
    if signal in frame.quant_features:
        return frame.quant_features[signal]
    return None


def _format_value_text(signal: str, value: float) -> str:
    if signal in {"ATRP_14", "BB_BANDWIDTH_20"}:
        return f"{value * 100:.1f}%"
    return f"{value:.3f}"


def _normalize_state(state: str | None) -> str | None:
    if not isinstance(state, str):
        return None
    normalized = state.strip()
    return normalized or None


def _build_current_reading_hint(
    *,
    signal: str,
    value: float,
    state: str | None,
) -> str:
    normalized_state = _normalize_state(state)
    if signal == "ADX_14":
        if value >= 25:
            return "The current reading suggests the market has a meaningful trend in place."
        if value <= 20:
            return "The current reading suggests the market is not in a particularly strong trend."
        return "The current reading suggests some directional structure, but not a fully established trend."
    if signal == "ATRP_14":
        return "The current reading points to the typical move size relative to price, which helps frame day-to-day risk."
    if signal == "ATR_14":
        return "The current reading shows the average absolute move size over the recent lookback window."
    if signal == "BB_BANDWIDTH_20":
        return "The current reading shows whether volatility is relatively compressed or already expanded."
    if signal == "FD_Z_SCORE":
        if abs(value) < 0.5:
            return "The current reading is close to neutral, so the signal is not far from its normal range."
        if value > 0:
            return "The current reading is above normal, which points to an upside statistical stretch."
        return "The current reading is below normal, which points to a downside statistical stretch."
    if signal == "FD_OPTIMAL_D":
        if value >= 0.6:
            return "The current reading suggests the market still carries noticeable trend memory or persistence."
        if value <= 0.3:
            return "The current reading suggests the series needs only limited adjustment to become more stable."
        return "The current reading suggests a moderate amount of trend memory remains in the series."
    if signal == "FD_ADF_STAT":
        if value <= -4.0:
            return "The current reading strongly supports the transformed series being stable enough for analysis."
        if value <= -3.0:
            return "The current reading supports the transformed series being reasonably stable."
        return "The current reading suggests the transformed series is less clearly stable."
    if normalized_state is not None:
        return f"The current state is {normalized_state.lower().replace('_', ' ')}."
    return f"The current reading is {value:.3f}."
