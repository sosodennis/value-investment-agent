from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.technical.domain.shared import TimeframeCode

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class RegimeFrame:
    timeframe: TimeframeCode
    regime: str
    confidence: float | None
    directional_bias: str
    adx: float | None = None
    atr_value: float | None = None
    atrp_value: float | None = None
    bollinger_bandwidth: float | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Scalar] = field(default_factory=dict)


@dataclass(frozen=True)
class RegimePack:
    ticker: str
    as_of: str
    timeframes: dict[TimeframeCode, RegimeFrame]
    regime_summary: dict[str, Scalar] = field(default_factory=dict)
