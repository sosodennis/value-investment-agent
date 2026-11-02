from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from .contracts import (
    GovernanceSummary,
    TechnicalGovernanceRegistry,
    TechnicalGovernanceReport,
)
from .drift_service import compare_registry_payloads
from .registry_service import registry_to_payload


def build_technical_governance_report(
    *,
    registry: TechnicalGovernanceRegistry,
    baseline_registry: TechnicalGovernanceRegistry | None,
    extra_issues: list[str] | None = None,
) -> TechnicalGovernanceReport:
    issues: list[str] = list(extra_issues or [])
    drifts = []
    if baseline_registry is not None:
        baseline_payload = registry_to_payload(baseline_registry)
        current_payload = registry_to_payload(registry)
        drift_items, drift_issues = compare_registry_payloads(
            baseline=baseline_payload,
            current=current_payload,
        )
        drifts = drift_items
        issues.extend(drift_issues)

    summary = GovernanceSummary(
        drift_count=len(drifts),
        drift_detected=bool(drifts),
        issues=tuple(issues),
    )

    return TechnicalGovernanceReport(
        schema_version="1.0",
        generated_at=datetime.now().isoformat(),
        registry=registry,
        baseline_registry=baseline_registry,
        drifts=tuple(drifts),
        summary=summary,
    )


def report_to_payload(report: TechnicalGovernanceReport) -> dict[str, object]:
    payload = asdict(report)
    payload["registry"] = registry_to_payload(report.registry)
    if report.baseline_registry is not None:
        payload["baseline_registry"] = registry_to_payload(report.baseline_registry)
    return payload


__all__ = [
    "build_technical_governance_report",
    "report_to_payload",
]
