from __future__ import annotations

import logging

import yfinance as yf

from src.agents.intent.application.ports import IntentCompanyProfileLookup
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)


def get_company_profile(ticker: str) -> IntentCompanyProfileLookup:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or "symbol" not in info:
            log_event(
                logger,
                event="intent_profile_not_found",
                message="company profile not found",
                level=logging.WARNING,
                error_code="INTENT_PROFILE_NOT_FOUND",
                fields={"ticker": ticker},
            )
            return IntentCompanyProfileLookup(
                profile=None,
                failure_code="INTENT_PROFILE_NOT_FOUND",
                failure_reason="profile missing symbol",
            )

        return IntentCompanyProfileLookup(
            profile=CompanyProfile(
                ticker=ticker,
                name=info.get("longName") or info.get("shortName") or ticker,
                sector=info.get("sector"),
                industry=info.get("industry"),
                description=info.get("longBusinessSummary"),
                market_cap=info.get("marketCap"),
                is_profitable=None,
            ),
        )
    except Exception as exc:
        log_event(
            logger,
            event="intent_profile_provider_failed",
            message="company profile provider failed",
            level=logging.ERROR,
            error_code="INTENT_PROFILE_PROVIDER_ERROR",
            fields={"ticker": ticker, "exception": bounded_text(exc)},
        )
        return IntentCompanyProfileLookup(
            profile=None,
            failure_code="INTENT_PROFILE_PROVIDER_ERROR",
            failure_reason=bounded_text(exc),
        )
