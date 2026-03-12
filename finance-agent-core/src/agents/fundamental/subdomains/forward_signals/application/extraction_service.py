from __future__ import annotations

import logging
from collections.abc import Mapping

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportModel,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.subdomains.forward_signals.interface.parsers import (
    parse_forward_signals,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

from .ports import ForwardSignalTextExtractor, ForwardSignalXbrlExtractor

logger = get_logger(__name__)


def extract_forward_signals(
    *,
    ticker: str,
    reports_raw: list[JSONObject],
    extract_xbrl_fn: ForwardSignalXbrlExtractor,
    extract_text_fn: ForwardSignalTextExtractor,
) -> list[ForwardSignalPayload] | None:
    canonical_reports = _parse_financial_reports(reports_raw)
    rules_sector = _infer_rules_sector_from_reports_raw(reports_raw)

    signals: list[dict[str, object]] = []
    try:
        xbrl_signals = extract_xbrl_fn(ticker=ticker, reports=canonical_reports)
        if xbrl_signals:
            signals.extend(xbrl_signals)
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_forward_signal_producer_failed",
            message="forward signal producer failed; proceeding without signals",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_FORWARD_SIGNAL_PRODUCER_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )

    try:
        text_signals = extract_text_fn(ticker=ticker, rules_sector=rules_sector)
        if text_signals:
            signals.extend(text_signals)
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_failed",
            message="forward signal text producer failed; proceeding without text signals",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_FORWARD_SIGNAL_TEXT_PRODUCER_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )

    return parse_forward_signals(signals, context="forward_signals.extracted")


def _parse_financial_reports(
    reports_raw: list[JSONObject],
) -> list[FinancialReportModel]:
    if not isinstance(reports_raw, list):
        raise TypeError("forward_signals.reports must be a list")
    parsed: list[FinancialReportModel] = []
    for index, report in enumerate(reports_raw):
        try:
            parsed.append(FinancialReportModel.model_validate(report))
        except Exception as exc:  # pragma: no cover - defensive for parse failures
            log_event(
                logger,
                event="fundamental_forward_signal_report_parse_failed",
                message="forward signal report parse failed; skipping xbrl signals",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_FORWARD_SIGNAL_REPORT_PARSE_FAILED",
                fields={
                    "index": index,
                    "exception": str(exc),
                },
            )
            return []
    return parsed


def _infer_rules_sector_from_reports_raw(
    reports_raw: list[JSONObject],
) -> str | None:
    for report in reports_raw:
        if not isinstance(report, Mapping):
            continue
        raw_type = report.get("industry_type")
        if raw_type is None:
            continue
        normalized = str(raw_type).strip().lower()
        if not normalized:
            continue
        if "financial" in normalized:
            return "financials"
    return None


__all__ = ["extract_forward_signals"]
