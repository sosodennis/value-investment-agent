import logging
import os
import traceback
from datetime import date

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)

from .factory import FinancialReportFactory
from .filing_fetcher import call_with_sec_retry
from .forward_signals import extract_forward_signals_from_xbrl_reports
from .forward_signals_text import extract_forward_signals_from_sec_text
from .report_contracts import (
    FinancialReport,
    IndustrialExtension,
)

logger = get_logger(__name__)
_XBRL_DIAGNOSTICS_ENABLED = os.getenv("FUNDAMENTAL_XBRL_DIAG", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}


def fetch_financial_data(ticker: str, years: int = 3) -> list[FinancialReport]:
    """
    Fetch financial data using the SECReportExtractor via FinancialReportFactory.
    Returns a list of FinancialReport objects containing Base and Extension models.
    """
    reports: list[FinancialReport] = []
    log_event(
        logger,
        event="fundamental_xbrl_fetch_started",
        message="xbrl financial data fetch started",
        fields={"ticker": ticker, "years": years},
    )

    fetched_years: set[int] = set()
    anchor_year: int | None = None

    try:
        log_event(
            logger,
            event="fundamental_xbrl_latest_attempt",
            message="xbrl latest filing fetch attempt",
            fields={"ticker": ticker},
        )
        latest_report = call_with_sec_retry(
            operation="create_report_latest",
            ticker=ticker,
            execute=lambda: FinancialReportFactory.create_latest_report(ticker),
        )
        latest_year = _report_year(latest_report)
        if latest_year is not None:
            fetched_years.add(latest_year)
            anchor_year = latest_year
        reports.append(latest_report)
        log_event(
            logger,
            event="fundamental_xbrl_latest_success",
            message="xbrl latest filing fetched",
            fields={
                "ticker": ticker,
                "actual_year": latest_year,
                "filing_metadata": latest_report.filing_metadata,
            },
        )
    except ValueError as exc:
        log_event(
            logger,
            event="fundamental_xbrl_latest_not_found",
            message="xbrl latest filing not found; fallback to fiscal year probing",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_LATEST_NOT_FOUND",
            fields={
                "ticker": ticker,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        )
    except Exception as exc:
        fields: dict[str, object] = {
            "ticker": ticker,
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }
        if _XBRL_DIAGNOSTICS_ENABLED:
            fields["traceback"] = traceback.format_exc(limit=25)
        log_event(
            logger,
            event="fundamental_xbrl_latest_failed",
            message="xbrl latest filing fetch failed; fallback to fiscal year probing",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_XBRL_LATEST_FETCH_FAILED",
            fields=fields,
        )

    current_year = date.today().year
    start_year = (anchor_year - 1) if anchor_year is not None else (current_year - 1)
    attempt_year = start_year
    while len(reports) < years and attempt_year > (start_year - years - 5):
        current_attempt_year = attempt_year
        try:
            log_event(
                logger,
                event="fundamental_xbrl_year_attempt",
                message="xbrl yearly report fetch attempt",
                fields={"ticker": ticker, "attempt_year": current_attempt_year},
            )
            report = call_with_sec_retry(
                operation=f"create_report_{current_attempt_year}",
                ticker=ticker,
                execute=lambda year=current_attempt_year: FinancialReportFactory.create_report(
                    ticker, year
                ),
            )

            actual_year = _report_year(report)
            if actual_year is None:
                log_event(
                    logger,
                    event="fundamental_xbrl_year_unknown",
                    message="xbrl report fetched but fiscal year missing; skipping",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_XBRL_YEAR_UNKNOWN",
                    fields={
                        "ticker": ticker,
                        "attempt_year": current_attempt_year,
                    },
                )
            elif actual_year in fetched_years:
                log_event(
                    logger,
                    event="fundamental_xbrl_duplicate_skipped",
                    message="duplicate xbrl report skipped",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_XBRL_DUPLICATE",
                    fields={
                        "ticker": ticker,
                        "actual_year": actual_year,
                        "attempt_year": current_attempt_year,
                    },
                )
            else:
                reports.append(report)
                fetched_years.add(actual_year)
                log_event(
                    logger,
                    event="fundamental_xbrl_year_success",
                    message="xbrl yearly report fetched",
                    fields={
                        "ticker": ticker,
                        "actual_year": actual_year,
                        "attempt_year": current_attempt_year,
                    },
                )
        except ValueError as exc:
            log_event(
                logger,
                event="fundamental_xbrl_year_not_found",
                message="xbrl yearly report not found",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_NOT_FOUND",
                fields={
                    "ticker": ticker,
                    "attempt_year": current_attempt_year,
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            )
        except Exception as exc:
            fields: dict[str, object] = {
                "ticker": ticker,
                "attempt_year": current_attempt_year,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            }
            if _XBRL_DIAGNOSTICS_ENABLED:
                fields["traceback"] = traceback.format_exc(limit=25)
            log_event(
                logger,
                event="fundamental_xbrl_year_failed",
                message="xbrl yearly report fetch failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_XBRL_FETCH_FAILED",
                fields=fields,
            )

        attempt_year -= 1

    reports.sort(key=lambda report: _report_year(report) or -1, reverse=True)
    _apply_cross_period_derivatives(reports)

    return reports


def fetch_financial_payload(ticker: str, years: int = 3) -> dict[str, object]:
    reports = fetch_financial_data(ticker, years=years)
    rules_sector = _infer_rules_sector_from_reports(reports)
    forward_signals: list[dict[str, object]] = []
    try:
        xbrl_signals = extract_forward_signals_from_xbrl_reports(
            ticker=ticker,
            reports=reports,
        )
        if xbrl_signals:
            forward_signals.extend(xbrl_signals)
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
        text_signals = extract_forward_signals_from_sec_text(
            ticker=ticker,
            rules_sector=rules_sector,
        )
        if text_signals:
            forward_signals.extend(text_signals)
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_failed",
            message="forward signal text producer failed; proceeding without text signals",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_FORWARD_SIGNAL_TEXT_PRODUCER_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )

    return {
        "financial_reports": reports,
        "forward_signals": forward_signals,
    }


def _infer_rules_sector_from_reports(reports: list[FinancialReport]) -> str | None:
    for report in reports:
        normalized_type = str(report.industry_type or "").strip().lower()
        if not normalized_type:
            continue
        if "financial" in normalized_type:
            return "financials"
    return None


def _report_year(report: FinancialReport) -> int | None:
    raw = report.base.fiscal_year.value
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(float(raw))
        except ValueError:
            return None
    return None


def _apply_cross_period_derivatives(reports: list[FinancialReport]) -> None:
    if len(reports) < 2:
        return

    def report_year(report: FinancialReport) -> int:
        value = report.base.fiscal_year.value
        if value is None:
            return -1
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def calc_delta(
        current: TraceableField[float],
        previous: TraceableField[float],
        name: str,
        expression: str,
    ) -> TraceableField[float]:
        if current.value is None or previous.value is None:
            return TraceableField(
                name=name,
                value=None,
                provenance=ManualProvenance(
                    description=f"Missing inputs for {expression}"
                ),
            )
        value = float(current.value) - float(previous.value)
        return TraceableField(
            name=name,
            value=value,
            provenance=ComputedProvenance(
                op_code="SUB",
                expression=expression,
                inputs={
                    "Current": current,
                    "Previous": previous,
                },
            ),
        )

    def calc_reinvestment_rate(
        capex: TraceableField[float] | None,
        da: TraceableField[float],
        wc_delta: TraceableField[float],
        nopat: TraceableField[float],
    ) -> TraceableField[float]:
        if capex is None:
            return TraceableField(
                name="Reinvestment Rate",
                value=None,
                provenance=ManualProvenance(
                    description="Missing CapEx for reinvestment rate"
                ),
            )
        if (
            capex.value is None
            or da.value is None
            or wc_delta.value is None
            or nopat.value in (None, 0)
        ):
            return TraceableField(
                name="Reinvestment Rate",
                value=None,
                provenance=ManualProvenance(
                    description="Missing inputs for reinvestment rate"
                ),
            )
        value = (float(capex.value) - float(da.value) + float(wc_delta.value)) / float(
            nopat.value
        )
        return TraceableField(
            name="Reinvestment Rate",
            value=value,
            provenance=ComputedProvenance(
                op_code="REINVESTMENT_RATE",
                expression="(CapEx - D&A + delta WC) / NOPAT",
                inputs={
                    "CapEx": capex,
                    "Depreciation & Amortization": da,
                    "Working Capital Delta": wc_delta,
                    "NOPAT": nopat,
                },
            ),
        )

    reports_sorted = sorted(reports, key=report_year, reverse=True)
    for idx, report in enumerate(reports_sorted):
        if idx + 1 >= len(reports_sorted):
            continue
        prev = reports_sorted[idx + 1]

        wc_delta = calc_delta(
            report.base.working_capital,
            prev.base.working_capital,
            "Working Capital Delta",
            "WorkingCapital(Current) - WorkingCapital(Previous)",
        )
        report.base.working_capital_delta = wc_delta

        capex_tf = None
        if isinstance(report.extension, IndustrialExtension):
            capex_tf = report.extension.capex

        reinvestment_rate = calc_reinvestment_rate(
            capex_tf,
            report.base.depreciation_and_amortization,
            wc_delta,
            report.base.nopat,
        )
        report.base.reinvestment_rate = reinvestment_rate
