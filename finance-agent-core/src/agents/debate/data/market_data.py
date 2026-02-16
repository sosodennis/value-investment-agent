"""
Market Data Service for CAPM-based Hurdle Rate Calculation.
"""

from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
import yfinance as yf

# Use the project's custom logger
from src.shared.kernel.tools.logger import get_logger

logger = get_logger(__name__)

# --- Configuration Constants ---
DEFAULT_RISK_FREE_RATE = 0.045
DEFAULT_MARKET_RISK_PREMIUM = 0.05
DEFAULT_BENCHMARK = "SPY"
TRADING_DAYS = 252
LOOKBACK_DAYS = 365

# --- Volatility Constraints ---
VOLATILITY_FLOOR = 0.08
VOLATILITY_CEILING = 0.80

# --- Risk Profiles & Maps ---
STATIC_BETA_MAP = {
    "DEFENSIVE_VALUE": 0.7,
    "GROWTH_TECH": 1.5,
    "SPECULATIVE_CRYPTO_BIO": 3.5,
}

CRASH_IMPACT_MAP = {
    "DEFENSIVE_VALUE": -0.25,
    "GROWTH_TECH": -0.35,
    "SPECULATIVE_CRYPTO_BIO": -0.60,
}

DEFAULT_PAYOFF_MAP = {
    "SURGE": 0.25,
    "MODERATE_UP": 0.10,
    "FLAT": 0.0,
    "MODERATE_DOWN": -0.10,
    "CRASH": -0.25,
}


def _fetch_price_series(
    ticker: str, start_date: datetime, end_date: datetime
) -> pd.Series | None:
    """
    Internal helper to fetch and clean historical price data.
    """
    try:
        raw_data = yf.download(
            ticker,
            start=start_date,
            end=end_date,
            progress=False,
            auto_adjust=True,
        )

        if raw_data.empty:
            logger.warning(f"⚠️ No data returned for {ticker}")
            return None

        cols = raw_data.columns
        if isinstance(cols, pd.MultiIndex):
            if "Adj Close" in cols.levels[0]:
                data = raw_data["Adj Close"]
            elif "Close" in cols.levels[0]:
                data = raw_data["Close"]
            else:
                data = raw_data.iloc[:, 0]
        else:
            data = raw_data["Adj Close"] if "Adj Close" in cols else raw_data["Close"]

        if isinstance(data, pd.DataFrame):
            if ticker in data.columns:
                data = data[ticker]
            else:
                data = data.squeeze()

        if not isinstance(data, pd.Series):
            if isinstance(data, pd.DataFrame):
                data = data.iloc[:, 0]

        return data.dropna()

    except Exception as e:
        logger.warning(f"⚠️ Data fetch error for {ticker}: {e}")
        return None


def get_stock_beta(
    ticker: str,
    benchmark: str = DEFAULT_BENCHMARK,
    lookback_days: int = LOOKBACK_DAYS,
) -> float | None:
    """
    Calculate the real Beta using covariance method.
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        logger.info(f"📊 Fetching beta data for {ticker} vs {benchmark}...")

        stock_prices = _fetch_price_series(ticker, start_date, end_date)
        benchmark_prices = _fetch_price_series(benchmark, start_date, end_date)

        if stock_prices is None or benchmark_prices is None:
            return None

        df_combined = pd.concat([stock_prices, benchmark_prices], axis=1, join="inner")
        if len(df_combined) < 30:
            logger.warning(f"⚠️ Insufficient overlapping data points for {ticker}")
            return None

        returns = df_combined.pct_change().dropna()
        stock_ret = returns.iloc[:, 0]
        bench_ret = returns.iloc[:, 1]

        covariance = np.cov(stock_ret, bench_ret)[0, 1]
        market_variance = np.var(bench_ret)

        if market_variance == 0:
            return None

        beta = covariance / market_variance
        logger.info(f"✅ Calculated Beta for {ticker}: {beta:.2f}")
        return float(beta)

    except Exception:
        logger.error(f"❌ Beta calculation failed for {ticker}", exc_info=True)
        return None


def calculate_capm_hurdle(
    ticker: str,
    risk_profile: str,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    market_risk_premium: float = DEFAULT_MARKET_RISK_PREMIUM,
) -> tuple[float, float, str]:
    """
    Calculate CAPM-based hurdle rate with fallback logic.
    """
    beta = get_stock_beta(ticker)
    data_source = "REAL_TIME"

    if beta is None:
        beta = STATIC_BETA_MAP.get(risk_profile.upper(), 1.5)
        data_source = "STATIC_FALLBACK"
        logger.warning(f"⚠️ Using static Beta ({beta}) for {ticker}")

    annual_hurdle = risk_free_rate + (beta * market_risk_premium)
    quarterly_hurdle = annual_hurdle / 4.0

    logger.info(
        f"📈 CAPM: {ticker} | Hurdle: {quarterly_hurdle:.1%} (Q) | Beta: {beta:.2f} [{data_source}]"
    )
    return float(quarterly_hurdle), float(beta), data_source


@lru_cache(maxsize=1)
def get_current_risk_free_rate() -> float:
    """
    動態獲取當前美國 3個月期國庫券 (Risk-Free Rate)。
    """
    try:
        ticker = yf.Ticker("^IRX")
        hist = ticker.history(period="5d")
        if hist.empty:
            return DEFAULT_RISK_FREE_RATE / 4.0

        annual_yield_percent = hist["Close"].iloc[-1]
        annual_yield_decimal = annual_yield_percent / 100.0

        quarterly_yield = annual_yield_decimal / 4.0
        logger.info(f"📊 Dynamic Risk-Free Rate fetched: {quarterly_yield:.4%} (Q)")
        return float(quarterly_yield)

    except Exception as e:
        logger.warning(
            f"⚠️ Failed to fetch dynamic risk-free rate: {e}. Using fallback."
        )
        return DEFAULT_RISK_FREE_RATE / 4.0


def get_dynamic_crash_impact(risk_profile: str) -> float:
    """Get theory-based crash impact (VaR)."""
    return CRASH_IMPACT_MAP.get(risk_profile.upper(), -0.25)


def get_dynamic_payoff_map(
    ticker: str,
    risk_profile: str = "GROWTH_TECH",
) -> dict[str, float]:
    """
    Generate volatility-based payoff map.
    """
    sector_crash = get_dynamic_crash_impact(risk_profile)
    fallback_map = {**DEFAULT_PAYOFF_MAP, "CRASH": sector_crash}

    if not ticker:
        return fallback_map

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        prices = _fetch_price_series(ticker, start_date, end_date)

        if prices is None or len(prices) < 60:
            logger.warning(f"⚠️ Insufficient volatility data for {ticker}")
            return fallback_map

        returns = prices.pct_change().dropna()
        daily_vol = float(returns.std())

        annual_vol = daily_vol * np.sqrt(TRADING_DAYS)
        quarterly_vol = annual_vol / 2.0

        quarterly_vol = np.clip(quarterly_vol, VOLATILITY_FLOOR, VOLATILITY_CEILING)

        dynamic_map = {
            "SURGE": float(round(quarterly_vol * 2.0, 3)),
            "MODERATE_UP": float(round(quarterly_vol * 1.0, 3)),
            "FLAT": 0.0,
            "MODERATE_DOWN": float(round(-quarterly_vol * 1.0, 3)),
            "CRASH": float(sector_crash),
        }

        logger.info(
            f"💰 {ticker} Vol Map: Q_Vol={quarterly_vol:.1%} | "
            f"Surge={dynamic_map['SURGE']} Crash={dynamic_map['CRASH']}"
        )
        return dynamic_map

    except Exception:
        logger.error(f"❌ Payoff map generation failed for {ticker}", exc_info=True)
        return fallback_map
