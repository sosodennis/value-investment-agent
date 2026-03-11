from __future__ import annotations

from src.agents.fundamental.infrastructure.sec_xbrl.quality.dqc_efm_gate_service import (
    FUNDAMENTAL_XBRL_QUALITY_BLOCKED,
    evaluate_xbrl_quality_gates,
    normalize_dqc_efm_issue,
)
from src.agents.fundamental.infrastructure.sec_xbrl.report_contracts import (
    BaseFinancialModel,
    FinancialReport,
)
from src.shared.kernel.traceable import ManualProvenance, TraceableField


def _report_with_missing_critical_fields() -> FinancialReport:
    return FinancialReport(
        base=BaseFinancialModel(
            total_revenue=TraceableField(
                name="Total Revenue",
                value=None,
                provenance=ManualProvenance(description="test"),
            ),
            operating_income=TraceableField(
                name="Operating Income",
                value=None,
                provenance=ManualProvenance(description="test"),
            ),
            income_before_tax=TraceableField(
                name="Income Before Tax",
                value=100.0,
                provenance=ManualProvenance(description="test"),
            ),
            income_tax_expense=TraceableField(
                name="Income Tax Expense",
                value=10.0,
                provenance=ManualProvenance(description="test"),
            ),
            total_debt=TraceableField(
                name="Total Debt",
                value=200.0,
                provenance=ManualProvenance(description="test"),
            ),
            cash_and_equivalents=TraceableField(
                name="Cash",
                value=50.0,
                provenance=ManualProvenance(description="test"),
            ),
            shares_outstanding=TraceableField(
                name="Shares Outstanding",
                value=None,
                provenance=ManualProvenance(description="test"),
            ),
        ),
        industry_type="Industrial",
        extension_type="Industrial",
    )


def test_quality_gate_blocks_when_critical_fields_missing() -> None:
    gates = evaluate_xbrl_quality_gates(
        reports_raw=[_report_with_missing_critical_fields()],
        diagnostics=None,
    )
    assert gates["status"] == "block"
    assert gates["blocking_error_code"] == FUNDAMENTAL_XBRL_QUALITY_BLOCKED
    assert int(gates["blocking_count"]) >= 1


def test_quality_gate_warns_for_non_critical_dqc_issue() -> None:
    gates = evaluate_xbrl_quality_gates(
        reports_raw=[],
        diagnostics={
            "dqc_efm_issues": [
                {
                    "code": "DQC_NON_CRITICAL_DIMENSION",
                    "source": "DQC",
                    "severity": "warning",
                    "field_key": "inventory",
                    "message": "dimension inconsistency",
                }
            ]
        },
    )
    assert gates["status"] == "warn"
    assert gates.get("blocking_error_code") is None
    assert gates["warning_count"] == 1


def test_quality_gate_blocks_for_efm_error() -> None:
    gates = evaluate_xbrl_quality_gates(
        reports_raw=[],
        diagnostics={
            "dqc_efm_issues": [
                {
                    "code": "EFM_CONTEXT_ERROR",
                    "source": "EFM",
                    "severity": "error",
                    "message": "invalid context",
                }
            ]
        },
    )
    assert gates["status"] == "block"
    assert gates["blocking_count"] == 1


def test_normalize_dqc_efm_issue_preserves_explicit_blocking() -> None:
    normalized = normalize_dqc_efm_issue(
        {
            "code": "DQC.US.0099",
            "source": "DQC",
            "severity": "warning",
            "field_key": "income_before_tax",
            "message": "sample",
            "blocking": True,
            "concept": "us-gaap:IncomeBeforeTax",
            "context_id": "ctx_2025",
        }
    )
    assert isinstance(normalized, dict)
    assert normalized.get("blocking") is True
    assert normalized.get("concept") == "us-gaap:IncomeBeforeTax"
    assert normalized.get("context_id") == "ctx_2025"
