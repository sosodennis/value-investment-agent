from datetime import date

from edgar import set_identity

from src.common.tools.logger import get_logger

from ..factories import FinancialReportFactory
from ..financial_models import FinancialReport

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

    return reports
