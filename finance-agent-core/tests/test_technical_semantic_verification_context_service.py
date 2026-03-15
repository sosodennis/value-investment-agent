from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agents.technical.application.semantic_verification_context_service import (
    assemble_verification_context,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalBacktestSummaryData,
    TechnicalVerificationReportArtifactData,
    TechnicalWfaSummaryData,
)


@dataclass
class _FakeVerificationPort:
    report: TechnicalVerificationReportArtifactData | None

    async def load_verification_report(
        self, artifact_id: str | None
    ) -> TechnicalVerificationReportArtifactData | None:
        return self.report


@pytest.mark.asyncio
async def test_assemble_verification_context_missing_report_id() -> None:
    port = _FakeVerificationPort(report=None)

    result = await assemble_verification_context(
        technical_port=port,
        verification_report_id=None,
    )

    assert result.is_degraded is True
    assert result.failure_code == "TECHNICAL_VERIFICATION_REPORT_MISSING"
    assert result.backtest_context == ""
    assert result.wfa_context == ""


@pytest.mark.asyncio
async def test_assemble_verification_context_formats_summary() -> None:
    report = TechnicalVerificationReportArtifactData(
        schema_version="1.0",
        ticker="AAPL",
        as_of="2025-01-01",
        backtest_summary=TechnicalBacktestSummaryData(
            strategy_name="Z-Mean",
            win_rate=0.55,
            profit_factor=1.4,
            sharpe_ratio=1.1,
            max_drawdown=0.2,
            total_trades=12,
        ),
        wfa_summary=TechnicalWfaSummaryData(
            wfa_sharpe=0.8,
            wfe_ratio=0.6,
            wfa_max_drawdown=0.15,
            period_count=4,
        ),
        robustness_flags=["LOW_SAMPLE"],
        baseline_gates={
            "status": "pass",
            "blocking_count": 0,
            "warning_count": 1,
            "issues": [{"code": "BACKTEST_LOW_SAMPLE"}],
        },
        degraded_reasons=None,
    )
    port = _FakeVerificationPort(report=report)

    result = await assemble_verification_context(
        technical_port=port,
        verification_report_id="vr1",
    )

    assert result.is_degraded is False
    assert "Baseline Gate" in result.backtest_context
    assert "Strategy" in result.backtest_context
    assert "WFA Sharpe" in result.wfa_context
