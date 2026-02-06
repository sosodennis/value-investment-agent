import yfinance as yf

from src.common.tools.logger import get_logger

from ..structures import CompanyProfile

logger = get_logger(__name__)


def get_company_profile(ticker: str) -> CompanyProfile | None:
    """
    Retrieve company profile using yfinance.

    Args:
        ticker: Stock ticker symbol

    Returns:
        CompanyProfile with sector, industry, and other metadata
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or "symbol" not in info:
            logger.warning(f"No profile found for ticker: {ticker}")
            return None

        profile = CompanyProfile(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector"),
            industry=info.get("industry"),
            description=info.get("longBusinessSummary"),
            market_cap=info.get("marketCap"),
            is_profitable=None,  # Placeholder, logic for profitability check remains outside
        )

        return profile

    except Exception:
        return None


def validate_ticker(ticker: str) -> bool:
    """
    Validate that a ticker exists and is tradeable.

    Args:
        ticker: Stock ticker symbol

    Returns:
        True if ticker is valid
    """
    profile = get_company_profile(ticker)
    return profile is not None
