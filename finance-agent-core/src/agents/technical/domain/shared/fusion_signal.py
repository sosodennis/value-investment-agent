from __future__ import annotations

from dataclasses import dataclass, field

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class FusionDiagnostics:
    confluence_matrix: dict[str, dict[str, Scalar]] = field(default_factory=dict)
    conflict_reasons: list[str] = field(default_factory=list)
    alignment_report_id: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FusionSignal:
    ticker: str
    as_of: str
    direction: str
    risk_level: str
    confidence: float | None = None
    diagnostics: FusionDiagnostics | None = None
