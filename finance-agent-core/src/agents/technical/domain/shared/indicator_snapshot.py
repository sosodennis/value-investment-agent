from __future__ import annotations

from dataclasses import dataclass, field

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class IndicatorSnapshot:
    name: str
    value: float | None
    state: str | None = None
    metadata: dict[str, Scalar] = field(default_factory=dict)
