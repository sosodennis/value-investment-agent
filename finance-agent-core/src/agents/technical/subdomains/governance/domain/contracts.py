from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GovernanceDrift:
    path: str
    expected: object
    actual: object


@dataclass(frozen=True)
class GovernanceSummary:
    drift_count: int
    drift_detected: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class TechnicalGovernanceRegistry:
    schema_version: str
    as_of: str
    fusion_model_version: str
    guardrail_version: str
    calibration_mapping_version: str
    calibration_mapping_source: str
    calibration_mapping_path: str | None
    calibration_degraded_reason: str | None
    calibration_method: str
    calibration_config: dict[str, object]


@dataclass(frozen=True)
class TechnicalGovernanceReport:
    schema_version: str
    generated_at: str
    registry: TechnicalGovernanceRegistry
    baseline_registry: TechnicalGovernanceRegistry | None
    drifts: tuple[GovernanceDrift, ...]
    summary: GovernanceSummary


__all__ = [
    "GovernanceDrift",
    "GovernanceSummary",
    "TechnicalGovernanceRegistry",
    "TechnicalGovernanceReport",
]
