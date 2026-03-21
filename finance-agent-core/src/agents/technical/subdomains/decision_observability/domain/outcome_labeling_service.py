from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from src.agents.technical.subdomains.decision_observability.domain.contracts import (
    HorizonResolution,
    OutcomeLabelingRequest,
    OutcomeLabelingResult,
    TechnicalOutcomePathRecord,
    TechnicalPredictionEventRecord,
)

_HORIZON_DELTAS = {
    "1d": timedelta(days=1),
    "5d": timedelta(days=5),
    "20d": timedelta(days=20),
}
_OUTCOME_LABELING_METHOD_VERSION = "technical_outcome_labeling.v1"


@dataclass(frozen=True)
class PricePathWindow:
    frame: pd.DataFrame
    entry_time: datetime
    exit_time: datetime


def build_outcome_labeling_request(
    *,
    event: TechnicalPredictionEventRecord,
    as_of_time: datetime,
    labeling_method_version: str = _OUTCOME_LABELING_METHOD_VERSION,
) -> OutcomeLabelingRequest:
    maturity_time = (
        normalize_utc_datetime(event.event_time) + resolve_horizon(event.horizon).delta
    )
    return OutcomeLabelingRequest(
        event=event,
        as_of_time=normalize_utc_datetime(as_of_time),
        maturity_time=maturity_time,
        labeling_method_version=labeling_method_version,
    )


def is_request_matured(request: OutcomeLabelingRequest) -> bool:
    return request.as_of_time >= request.maturity_time


def resolve_horizon(horizon: str) -> HorizonResolution:
    delta = _HORIZON_DELTAS.get(horizon)
    if delta is None:
        raise ValueError(f"unsupported labeling horizon: {horizon}")
    return HorizonResolution(horizon=horizon, delta=delta)


def compute_outcome_label(
    *,
    request: OutcomeLabelingRequest,
    price_frame: pd.DataFrame,
) -> OutcomeLabelingResult:
    if not is_request_matured(request):
        raise ValueError("outcome labeling request is not matured")

    window = build_price_path_window(
        event=request.event,
        maturity_time=request.maturity_time,
        price_frame=price_frame,
    )
    entry_close = float(window.frame["close"].iloc[0])
    exit_close = float(window.frame["close"].iloc[-1])
    direction_multiplier = _direction_multiplier(request.event.direction)

    forward_return = _signed_return(
        start_value=entry_close,
        end_value=exit_close,
        direction_multiplier=direction_multiplier,
    )
    favorable_price, adverse_price = _resolve_excursion_prices(
        price_frame=window.frame,
        direction_multiplier=direction_multiplier,
    )
    mfe = _signed_return(
        start_value=entry_close,
        end_value=favorable_price,
        direction_multiplier=direction_multiplier,
    )
    mae = _signed_return(
        start_value=entry_close,
        end_value=adverse_price,
        direction_multiplier=direction_multiplier,
    )

    data_quality_flags = tuple(_build_data_quality_flags(window.frame))
    outcome = TechnicalOutcomePathRecord(
        outcome_path_id=str(uuid.uuid4()),
        event_id=request.event.event_id,
        resolved_at=request.maturity_time.replace(tzinfo=None),
        forward_return=forward_return,
        mfe=mfe,
        mae=mae,
        realized_volatility=_compute_realized_volatility(window.frame["close"]),
        labeling_method_version=request.labeling_method_version,
        data_quality_flags=data_quality_flags,
    )
    return OutcomeLabelingResult(
        outcome=outcome,
        source_row_count=len(window.frame),
        entry_time=window.entry_time,
        exit_time=window.exit_time,
        is_matured=True,
        data_quality_flags=data_quality_flags,
    )


def build_price_path_window(
    *,
    event: TechnicalPredictionEventRecord,
    maturity_time: datetime,
    price_frame: pd.DataFrame,
) -> PricePathWindow:
    if price_frame.empty:
        raise ValueError("empty price frame")
    normalized = _normalize_price_frame(price_frame)
    event_time = normalize_utc_datetime(event.event_time)
    matured = normalize_utc_datetime(maturity_time)
    window = normalized.loc[
        (normalized.index >= event_time) & (normalized.index <= matured)
    ]
    if window.empty:
        raise ValueError("no price path rows available for labeling window")
    return PricePathWindow(
        frame=window,
        entry_time=_to_utc_datetime(window.index[0]),
        exit_time=_to_utc_datetime(window.index[-1]),
    )


def filter_matured_events(
    *,
    events: list[TechnicalPredictionEventRecord],
    as_of_time: datetime,
) -> list[OutcomeLabelingRequest]:
    requests: list[OutcomeLabelingRequest] = []
    for event in events:
        request = build_outcome_labeling_request(
            event=event,
            as_of_time=as_of_time,
        )
        if is_request_matured(request):
            requests.append(request)
    return requests


def normalize_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_price_frame(price_frame: pd.DataFrame) -> pd.DataFrame:
    normalized = price_frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index, utc=True, errors="coerce")
    elif normalized.index.tz is None:
        normalized.index = normalized.index.tz_localize(UTC)
    else:
        normalized.index = normalized.index.tz_convert(UTC)
    normalized = normalized.sort_index()
    return normalized


def _to_utc_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


def _direction_multiplier(direction: str) -> float:
    normalized = direction.upper()
    if "BEAR" in normalized:
        return -1.0
    if "NEUTRAL" in normalized:
        return 1.0
    return 1.0


def _signed_return(
    *,
    start_value: float,
    end_value: float,
    direction_multiplier: float,
) -> float | None:
    if start_value <= 0:
        return None
    raw_return = (end_value / start_value) - 1.0
    return float(raw_return * direction_multiplier)


def _resolve_excursion_prices(
    *,
    price_frame: pd.DataFrame,
    direction_multiplier: float,
) -> tuple[float, float]:
    high_value = (
        float(price_frame["high"].max())
        if "high" in price_frame
        else float(price_frame["close"].max())
    )
    low_value = (
        float(price_frame["low"].min())
        if "low" in price_frame
        else float(price_frame["close"].min())
    )
    if direction_multiplier < 0:
        return low_value, high_value
    return high_value, low_value


def _compute_realized_volatility(close_series: pd.Series) -> float | None:
    if len(close_series) < 2:
        return None
    returns = close_series.astype(float).pct_change().dropna()
    if returns.empty:
        return None
    return float(returns.std(ddof=0) * math.sqrt(252.0))


def _build_data_quality_flags(price_frame: pd.DataFrame) -> list[str]:
    flags: list[str] = []
    if len(price_frame) < 2:
        flags.append("SHORT_WINDOW")
    if price_frame[["close"]].isna().any().any():
        flags.append("MISSING_CLOSE_VALUES")
    if "high" in price_frame and price_frame["high"].isna().any():
        flags.append("MISSING_HIGH_VALUES")
    if "low" in price_frame and price_frame["low"].isna().any():
        flags.append("MISSING_LOW_VALUES")
    return flags


__all__ = [
    "OutcomeLabelingRequest",
    "OutcomeLabelingResult",
    "PricePathWindow",
    "build_outcome_labeling_request",
    "build_price_path_window",
    "compute_outcome_label",
    "filter_matured_events",
    "is_request_matured",
    "normalize_utc_datetime",
    "resolve_horizon",
]
