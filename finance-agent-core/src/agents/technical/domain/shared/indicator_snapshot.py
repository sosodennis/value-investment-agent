from __future__ import annotations

from dataclasses import dataclass, field

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class IndicatorProvenance:
    method: str | None = None
    input_basis: str | None = None
    source_timeframe: str | None = None
    calculation_version: str | None = None


@dataclass(frozen=True)
class IndicatorQuality:
    effective_sample_count: int | None = None
    minimum_samples: int | None = None
    warmup_status: str | None = None
    fidelity: str | None = None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorSnapshot:
    name: str
    value: float | None
    state: str | None = None
    provenance: IndicatorProvenance | None = None
    quality: IndicatorQuality | None = None
    metadata: dict[str, Scalar] = field(default_factory=dict)
