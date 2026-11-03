"""Offline release-gate runner for the independent Fundamental challenger."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .calculator import CalculationRefusal, calculate
from .replay import replay_calculation
from .verification import (
    VerificationRefusal,
    compare_artifact,
    independent_calculate,
    invariant_findings,
    load_cohort_manifest,
    make_report,
    mutation_findings,
    property_findings,
    request_for_case,
    verify_public_snapshot_bytes,
)


class ReleaseGateFailure(RuntimeError):
    """Raised by the CLI when the cohort cannot be released."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("fundamental verification release gate blocked")
        self.report = report


def run_release_gate(cohort_path: Path) -> dict[str, Any]:
    manifest, cases = load_cohort_manifest(cohort_path)
    source_records = verify_public_snapshot_bytes(cohort_path, cases)
    source_by_snapshot = {record["snapshot_id"]: record for record in source_records}
    positive = [case for case in cases if case.kind == "positive"]
    abstained = [case for case in cases if case.kind in {"abstain", "degraded"}]
    findings: list[str] = []
    case_reports: list[dict[str, Any]] = []
    model_counts: dict[str, int] = {}
    required_features = {
        "extension-heavy",
        "amended-filing",
        "sbc",
        "dilution",
        "share-class",
        "leases",
        "capital-bridge",
        "missing-fact",
        "conflicting-facts",
        "unsupported-sector",
    }
    feature_coverage = {feature for case in cases for feature in case.features}
    for feature in sorted(required_features - feature_coverage):
        findings.append(f"cohort:feature_missing:{feature}")

    if len(positive) < 10:
        findings.append("cohort:positive_count_below_10")
    if len(abstained) < 10:
        findings.append("cohort:abstention_count_below_10")
    for model_id in ("fcff_dcf", "transition_fcff_dcf"):
        model_count = sum(
            case.kind == "positive" and case.model_id == model_id for case in cases
        )
        model_counts[model_id] = model_count
        if model_count < 5:
            findings.append(f"cohort:{model_id}_positive_count_below_5")
    if len({case.sector for case in positive}) < 5:
        findings.append("cohort:positive_sector_count_below_5")

    for case in cases:
        request = request_for_case(manifest, case)
        actual = None
        actual_refusal = None
        try:
            actual = calculate(request)
        except CalculationRefusal as error:
            actual_refusal = error.code
        except (ArithmeticError, ValueError) as error:
            actual_refusal = f"UNEXPECTED:{type(error).__name__}"

        reference = None
        reference_refusal = None
        try:
            reference = independent_calculate(request)
        except VerificationRefusal as error:
            reference_refusal = error.code
        except (ArithmeticError, ValueError) as error:
            reference_refusal = f"UNEXPECTED:{type(error).__name__}"

        case_findings: list[str] = []
        replay_status = "not_run"
        source = source_by_snapshot[case.source_snapshot_id]
        for field in ("available_at", "filed_at"):
            timestamp = source.get(field)
            if (
                timestamp is not None
                and request.valuation_context.valuation_timestamp
                < datetime.fromisoformat(timestamp)
            ):
                case_findings.append(f"{case.case_id}:future_data:{field}")
        if case.kind == "positive":
            if actual is None:
                case_findings.append(f"{case.case_id}:production:{actual_refusal}")
            if reference is None:
                case_findings.append(f"{case.case_id}:challenger:{reference_refusal}")
            if actual is not None and reference is not None:
                case_findings.extend(
                    f"{case.case_id}:{finding}"
                    for finding in compare_artifact(reference, actual)
                )
                if actual.input_digest != request.input_digest:
                    case_findings.append(f"{case.case_id}:untraceable_input_digest")
                if not all(node.trace.expression for node in actual.nodes):
                    case_findings.append(f"{case.case_id}:untraceable_node_trace")
                if (
                    actual.calculation_status.value != "completed"
                    or actual.quality_status.value != "verified"
                ):
                    case_findings.append(f"{case.case_id}:invalid_completion_status")
                case_findings.extend(
                    f"{case.case_id}:{finding}"
                    for finding in invariant_findings(request, reference)
                )
                case_findings.extend(
                    f"{case.case_id}:{finding}"
                    for finding in property_findings(request)
                )
                case_findings.extend(
                    f"{case.case_id}:{finding}"
                    for finding in mutation_findings(request)
                )
                replay_status = replay_calculation(request, actual).status
                if replay_status != "match":
                    case_findings.append(
                        f"{case.case_id}:offline_replay:{replay_status}"
                    )
        else:
            expected = case.expected_refusal_code
            if not expected:
                case_findings.append(f"{case.case_id}:missing_expected_refusal_code")
            if not request.quality.missing_evidence:
                case_findings.append(f"{case.case_id}:missing_evidence_manifest")
            if actual is None and expected and actual_refusal != expected:
                case_findings.append(
                    f"{case.case_id}:production_reason:{actual_refusal}!={expected}"
                )
            if reference is None and expected and reference_refusal != expected:
                case_findings.append(
                    f"{case.case_id}:challenger_reason:{reference_refusal}!={expected}"
                )
            if actual is not None:
                case_findings.append(f"{case.case_id}:production_silent_fallback")
            if reference is not None:
                case_findings.append(f"{case.case_id}:challenger_silent_fallback")

        findings.extend(case_findings)
        case_reports.append(
            {
                "case_id": case.case_id,
                "kind": case.kind,
                "model_id": case.model_id,
                "sector": case.sector,
                "source_snapshot_id": case.source_snapshot_id,
                "features": case.features,
                "production": "completed" if actual is not None else actual_refusal,
                "challenger": "completed"
                if reference is not None
                else reference_refusal,
                "expected_refusal_code": case.expected_refusal_code,
                "issue_codes": request.quality.issue_codes,
                "missing_evidence": request.quality.missing_evidence,
                "fact_ids": request.provenance.fact_ids,
                "replay": replay_status,
                "findings": tuple(case_findings),
            }
        )

    counts = {
        "total": len(cases),
        "positive": len(positive),
        "abstain_or_degraded": len(abstained),
        "fcff_dcf_positive": model_counts["fcff_dcf"],
        "transition_fcff_dcf_positive": model_counts["transition_fcff_dcf"],
    }
    return make_report(
        cohort_id=manifest["cohort_id"],
        source_records=source_records,
        cases=tuple(case_reports),
        findings=tuple(findings),
        counts=counts,
        coverage_features=tuple(sorted(feature_coverage)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = run_release_gate(args.cohort)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["release_decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
