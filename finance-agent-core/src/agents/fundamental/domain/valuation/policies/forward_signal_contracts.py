from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEFAULT_FORWARD_SIGNAL_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_FORWARD_SIGNAL_MAX_ADJUSTMENT_BASIS_POINTS = 300.0

SUPPORTED_FORWARD_SIGNAL_METRICS: tuple[str, ...] = (
    "growth_outlook",
    "margin_outlook",
    "capex_outlook",
    "credit_cost_outlook",
)
SUPPORTED_FORWARD_SIGNAL_SOURCES: tuple[str, ...] = (
    "mda",
    "xbrl_auto",
    "earnings_call",
    "press_release",
    "news",
    "debate",
    "manual",
)
SUPPORTED_FORWARD_SIGNAL_DIRECTIONS: tuple[str, ...] = ("up", "down", "neutral")
SUPPORTED_FORWARD_SIGNAL_UNITS: tuple[str, ...] = ("basis_points", "ratio")


@dataclass(frozen=True)
class ForwardSignalSourceLocator:
    text_scope: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ForwardSignalEvidence:
    preview_text: str
    full_text: str
    source_url: str
    doc_type: str | None = None
    period: str | None = None
    filing_date: str | None = None
    accession_number: str | None = None
    focus_strategy: str | None = None
    extraction_rule: str | None = None
    source_locator: ForwardSignalSourceLocator | None = None


@dataclass(frozen=True)
class ForwardSignal:
    signal_id: str
    source_type: str
    metric: str
    direction: str
    value: float
    unit: str
    confidence: float
    as_of: str | None
    evidence: tuple[ForwardSignalEvidence, ...]


@dataclass(frozen=True)
class ForwardSignalDecision:
    signal_id: str
    metric: str
    accepted: bool
    reason: str
    effective_basis_points: float
    raw_basis_points: float
    calibrated_basis_points: float
    calibration_applied: bool
    mapping_version: str | None
    risk_tag: str | None


@dataclass(frozen=True)
class ForwardSignalPolicyResult:
    total_count: int
    accepted_count: int
    rejected_count: int
    evidence_count: int
    growth_adjustment: float
    margin_adjustment: float
    raw_growth_adjustment_basis_points: float
    raw_margin_adjustment_basis_points: float
    growth_adjustment_basis_points: float
    margin_adjustment_basis_points: float
    calibration_applied: bool
    mapping_version: str | None
    risk_level: Literal["low", "medium", "high"]
    source_types: tuple[str, ...]
    decisions: tuple[ForwardSignalDecision, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "signals_total": self.total_count,
            "signals_accepted": self.accepted_count,
            "signals_rejected": self.rejected_count,
            "evidence_count": self.evidence_count,
            "raw_growth_adjustment_basis_points": self.raw_growth_adjustment_basis_points,
            "raw_margin_adjustment_basis_points": self.raw_margin_adjustment_basis_points,
            "growth_adjustment_basis_points": self.growth_adjustment_basis_points,
            "margin_adjustment_basis_points": self.margin_adjustment_basis_points,
            "calibration_applied": self.calibration_applied,
            "mapping_version": self.mapping_version,
            "risk_level": self.risk_level,
            "source_types": list(self.source_types),
            "decisions": [
                {
                    "signal_id": decision.signal_id,
                    "metric": decision.metric,
                    "accepted": decision.accepted,
                    "reason": decision.reason,
                    "effective_basis_points": decision.effective_basis_points,
                    "raw_basis_points": decision.raw_basis_points,
                    "calibrated_basis_points": decision.calibrated_basis_points,
                    "calibration_applied": decision.calibration_applied,
                    "mapping_version": decision.mapping_version,
                    "risk_tag": decision.risk_tag,
                }
                for decision in self.decisions
            ],
        }
