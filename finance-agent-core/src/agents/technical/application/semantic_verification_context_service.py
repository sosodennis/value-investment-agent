from __future__ import annotations

import logging

from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    TechnicalPortLike,
)
from src.agents.technical.interface.semantic_context_formatter_service import (
    format_verification_backtest_summary_for_llm,
    format_verification_wfa_summary_for_llm,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


async def assemble_verification_context(
    *,
    technical_port: TechnicalPortLike,
    verification_report_id: str | None,
) -> BacktestContextResult:
    if not verification_report_id:
        log_event(
            logger,
            event="technical_semantic_verification_missing_report_id",
            message="technical semantic verification context missing report id",
            level=logging.WARNING,
            error_code="TECHNICAL_VERIFICATION_REPORT_MISSING",
            fields={
                "degrade_source": "semantic_verification_context",
                "fallback_mode": "continue_without_verification_context",
                "input_count": 0,
                "output_count": 0,
            },
        )
        return BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
            verification_report=None,
            is_degraded=True,
            failure_code="TECHNICAL_VERIFICATION_REPORT_MISSING",
        )

    try:
        report = await technical_port.load_verification_report(verification_report_id)
        if report is None:
            raise ValueError("Verification report not found")

        backtest_context = format_verification_backtest_summary_for_llm(report)
        wfa_context = format_verification_wfa_summary_for_llm(report)

        return BacktestContextResult(
            backtest_context=backtest_context,
            wfa_context=wfa_context,
            price_data=None,
            chart_data=None,
            verification_report=report,
            is_degraded=False,
            failure_code=None,
        )
    except Exception as exc:
        failure_code = "TECHNICAL_VERIFICATION_CONTEXT_FAILED"
        log_event(
            logger,
            event="technical_semantic_verification_context_failed",
            message="technical semantic verification context failed; proceeding without statistical verification",
            level=logging.WARNING,
            error_code=failure_code,
            fields={
                "exception": str(exc),
                "degrade_source": "semantic_verification_context",
                "fallback_mode": "continue_without_verification_context",
                "verification_report_id": verification_report_id,
                "input_count": 1,
                "output_count": 0,
            },
        )
        return BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=None,
            chart_data=None,
            verification_report=None,
            is_degraded=True,
            failure_code=failure_code,
        )
