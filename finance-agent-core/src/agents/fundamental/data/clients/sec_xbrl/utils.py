from datetime import date

from edgar import set_identity

from src.shared.kernel.tools.logger import get_logger
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)

from .factory import FinancialReportFactory
from .models import (
    FinancialReport,
    IndustrialExtension,
)

logger = get_logger(__name__)

# Set SEC EDGAR identity
set_identity("ValueInvestmentAgent research@example.com")


def fetch_financial_data(ticker: str, years: int = 3) -> list[FinancialReport]:
    """
    Fetch financial data using the SECReportExtractor via FinancialReportFactory.
    Returns a list of FinancialReport objects containing Base and Extension models.
    """
    reports = []
    logger.info(f"Fetching financial data for {ticker} (Last {years} years)...")

    current_year = date.today().year
    start_year = current_year - 1

    fetched_years = set()
    attempt_year = start_year

    while len(reports) < years and attempt_year > (start_year - years - 5):
        try:
            logger.info(f"Attempting to fetch report for FY{attempt_year}...")
            report = FinancialReportFactory.create_report(ticker, attempt_year)

            actual_year = report.base.fiscal_year.value

            if actual_year in fetched_years:
                logger.info(
                    f"ℹ️ Skipping duplicate report for FY{actual_year} (requested FY{attempt_year})"
                )
            else:
                reports.append(report)
                fetched_years.add(actual_year)
                logger.info(f"✅ Successfully fetched report for FY{actual_year}")
        except ValueError as ve:
            logger.warning(f"⚠️ Report not found for FY{attempt_year}: {ve}")
        except Exception as e:
            logger.error(f"❌ Error fetching report for FY{attempt_year}: {e}")

        attempt_year -= 1

    _apply_cross_period_derivatives(reports)

    return reports


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
