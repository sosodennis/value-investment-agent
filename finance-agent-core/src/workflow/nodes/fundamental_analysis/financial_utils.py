import logging
from datetime import date

from edgar import set_identity

from .factories import FinancialReportFactory
from .financial_models import FinancialReport

logger = logging.getLogger(__name__)

# Set SEC EDGAR identity
set_identity("ValueInvestmentAgent research@example.com")


def fetch_financial_data(ticker: str, years: int = 3) -> list[FinancialReport]:
    """
    Fetch financial data using the SECReportExtractor via FinancialReportFactory.
    Returns a list of FinancialReport objects containing Base and Extension models.
    """
    reports = []
    logger.info(f"Fetching financial data for {ticker} (Last {years} years)...")

    # Estimate the most recent completed fiscal year
    # If we are in early 2026, the 2025 10-K might not be out, so we start checking from 2024?
    # Or we can just try 2025 and fail, then 2024.
    # But SECReportExtractor raises ValueError if not found.

    current_year = date.today().year

    # Basic strategy: Try pulling for (Current Year - 1) down to (Current Year - Years)
    start_year = current_year - 1

    # We allow a small buffer; sometimes 'fiscal_year' for the extractor refers to index year.
    # Let's iterate.

    fetched_years = set()
    attempt_year = start_year

    # Try fetching until we have the requested number of unique reports or we've gone too far back
    while len(reports) < years and attempt_year > (start_year - years - 5):
        try:
            logger.info(f"Attempting to fetch report for FY{attempt_year}...")
            report = FinancialReportFactory.create_report(ticker, attempt_year)

            # Extract actual fiscal year from the report to detect duplicates
            # (SECReportExtractor might fall back to the latest report if the requested year is not found)
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
