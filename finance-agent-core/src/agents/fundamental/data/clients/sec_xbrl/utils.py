import logging
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
from .models import (
    FinancialReport,
    IndustrialExtension,
)

logger = get_logger(__name__)


def fetch_financial_data(ticker: str, years: int = 3) -> list[FinancialReport]:
    """
    Fetch financial data using the SECReportExtractor via FinancialReportFactory.
    Returns a list of FinancialReport objects containing Base and Extension models.
    """
    reports = []
    log_event(
        logger,
        event="fundamental_xbrl_fetch_started",
        message="xbrl financial data fetch started",
        fields={"ticker": ticker, "years": years},
    )

    current_year = date.today().year
    start_year = current_year - 1

    fetched_years = set()
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

            actual_year = report.base.fiscal_year.value

            if actual_year in fetched_years:
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
                    "exception": str(exc),
                },
            )
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_xbrl_year_failed",
                message="xbrl yearly report fetch failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_XBRL_FETCH_FAILED",
                fields={
                    "ticker": ticker,
                    "attempt_year": current_attempt_year,
                    "exception": str(exc),
                },
            )

        attempt_year -= 1

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
