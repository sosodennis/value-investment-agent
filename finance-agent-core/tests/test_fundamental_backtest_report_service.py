from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.fundamental.subdomains.core_valuation.domain.backtest import (
    CaseResult,
    build_report_payload,
)


def test_build_report_payload_includes_calibration_metadata() -> None:
    payload = build_report_payload(
        dataset_path=Path("dataset.json"),
        baseline_path=Path("baseline.json"),
        results=[
            CaseResult(
                case_id="case_1",
                model="dcf_standard",
                status="ok",
                metrics={"intrinsic_value": 123.0},
            )
        ],
        drifts=[],
        issues=["calibration_mapping_degraded:missing"],
        baseline_updated=False,
        calibration={
            "gate_passed": False,
            "mapping_version": "default-v1",
            "mapping_source": "embedded_default",
            "mapping_path": "/tmp/missing.json",
            "degraded_reason": "missing",
        },
    )

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["calibration_gate_passed"] is False
    assert payload["calibration"] == {
        "gate_passed": False,
        "mapping_version": "default-v1",
        "mapping_source": "embedded_default",
        "mapping_path": "/tmp/missing.json",
        "degraded_reason": "missing",
    }


def test_build_report_payload_defaults_to_passed_without_calibration_block() -> None:
    payload = build_report_payload(
        dataset_path=Path("dataset.json"),
        baseline_path=Path("baseline.json"),
        results=[],
        drifts=[],
        issues=[],
        baseline_updated=False,
    )

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["calibration_gate_passed"] is True
    assert payload["calibration"] == {}


def test_build_report_payload_includes_monitoring_summary_metrics() -> None:
    payload = build_report_payload(
        dataset_path=Path("dataset.json"),
        baseline_path=Path("baseline.json"),
        results=[
            CaseResult(
                case_id="case_1",
                model="dcf_growth",
                status="ok",
                metrics={
                    "intrinsic_value": 210.0,
                    "target_price_median": 180.0,
                    "upside_potential": 1.2,
                    "base_growth_guardrail_applied": True,
                    "base_capex_guardrail_applied": True,
                    "base_wc_guardrail_applied": False,
                    "shares_scope_mismatch_detected": True,
                    "shares_scope_mismatch_resolved": False,
                    "target_consensus_quality_bucket": "degraded",
                    "target_consensus_confidence_weight": 0.30,
                    "target_consensus_warning_codes": [
                        "provider_blocked",
                        "provider_fetch_failed",
                    ],
                },
            ),
            CaseResult(
                case_id="case_2",
                model="dcf_growth",
                status="ok",
                metrics={
                    "consensus_gap_pct": -0.1,
                    "upside_potential": 0.5,
                    "base_margin_guardrail_applied": False,
                    "base_capex_guardrail_applied": False,
                    "base_wc_guardrail_applied": False,
                    "shares_scope_mismatch_detected": True,
                    "shares_scope_mismatch_resolved": True,
                    "target_consensus_quality_bucket": "high",
                    "target_consensus_confidence_weight": 1.0,
                    "target_consensus_warning_codes": [
                        "provider_parse_missing",
                    ],
                },
            ),
            CaseResult(
                case_id="case_3",
                model="dcf_growth",
                status="error",
                error="failed",
            ),
        ],
        drifts=[],
        issues=[],
        baseline_updated=False,
    )

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["extreme_upside_rate"] == 0.5
    assert summary["guardrail_hit_rate"] == 0.5
    assert summary["reinvestment_guardrail_hit_rate"] == 0.5
    assert summary["shares_scope_mismatch_rate"] == 0.5
    assert summary["consensus_confidence_weight_avg"] == pytest.approx(0.65)
    assert summary["consensus_degraded_rate"] == pytest.approx(0.5)
    consensus_gap_distribution = summary["consensus_gap_distribution"]
    assert isinstance(consensus_gap_distribution, dict)
    assert consensus_gap_distribution["available_count"] == 2
    assert consensus_gap_distribution["median"] == pytest.approx(0.03333333333333333)
    consensus_quality_distribution = summary["consensus_quality_distribution"]
    assert isinstance(consensus_quality_distribution, dict)
    assert consensus_quality_distribution["available_count"] == 2
    assert consensus_quality_distribution["degraded_count"] == 1
    assert consensus_quality_distribution["high_count"] == 1
    warning_distribution = summary["consensus_warning_code_distribution"]
    assert isinstance(warning_distribution, dict)
    assert warning_distribution["available_count"] == 2
    assert warning_distribution["code_case_counts"]["provider_blocked"] == 1
    assert warning_distribution["code_case_counts"]["provider_parse_missing"] == 1
    assert warning_distribution["code_case_rates"]["provider_blocked"] == pytest.approx(
        0.5
    )
    assert warning_distribution["code_case_rates"][
        "provider_parse_missing"
    ] == pytest.approx(0.5)
    assert summary["consensus_provider_blocked_rate"] == pytest.approx(0.5)
    assert summary["consensus_parse_missing_rate"] == pytest.approx(0.5)


def test_build_report_payload_defaults_monitoring_metrics_when_unavailable() -> None:
    payload = build_report_payload(
        dataset_path=Path("dataset.json"),
        baseline_path=Path("baseline.json"),
        results=[
            CaseResult(
                case_id="case_1",
                model="dcf_growth",
                status="ok",
                metrics={"intrinsic_value": 100.0},
            )
        ],
        drifts=[],
        issues=[],
        baseline_updated=False,
    )

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["extreme_upside_rate"] == 0.0
    assert summary["guardrail_hit_rate"] == 0.0
    assert summary["reinvestment_guardrail_hit_rate"] == 0.0
    assert summary["shares_scope_mismatch_rate"] == 0.0
    assert summary["consensus_confidence_weight_avg"] == 0.0
    assert summary["consensus_degraded_rate"] == 0.0
    consensus_gap_distribution = summary["consensus_gap_distribution"]
    assert isinstance(consensus_gap_distribution, dict)
    assert consensus_gap_distribution == {"available_count": 0}
    consensus_quality_distribution = summary["consensus_quality_distribution"]
    assert isinstance(consensus_quality_distribution, dict)
    assert consensus_quality_distribution == {"available_count": 0}
    warning_distribution = summary["consensus_warning_code_distribution"]
    assert isinstance(warning_distribution, dict)
    assert warning_distribution == {"available_count": 0}
    assert summary["consensus_provider_blocked_rate"] == 0.0
    assert summary["consensus_parse_missing_rate"] == 0.0
