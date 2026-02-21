from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

import yfinance as yf

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

DEFAULT_RISK_FREE_RATE = 0.042
DEFAULT_BETA = 1.0


@dataclass(frozen=True)
class MarketSnapshot:
    current_price: float | None
    market_cap: float | None
    shares_outstanding: float | None
    beta: float | None
    risk_free_rate: float | None
    consensus_growth_rate: float | None
    target_mean_price: float | None
    as_of: str
    provider: str
    missing_fields: tuple[str, ...]
    source_warnings: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "current_price": self.current_price,
            "market_cap": self.market_cap,
            "shares_outstanding": self.shares_outstanding,
            "beta": self.beta,
            "risk_free_rate": self.risk_free_rate,
            "consensus_growth_rate": self.consensus_growth_rate,
            "target_mean_price": self.target_mean_price,
            "as_of": self.as_of,
            "provider": self.provider,
            "missing_fields": list(self.missing_fields),
            "source_warnings": list(self.source_warnings),
        }


class MarketDataClient:
    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.25,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._cache: dict[str, tuple[float, MarketSnapshot]] = {}

    def get_market_snapshot(self, ticker_symbol: str) -> MarketSnapshot:
        symbol = ticker_symbol.strip().upper()
        if not symbol:
            raise ValueError("ticker_symbol must not be empty")

        cached = self._cache.get(symbol)
        now_ts = time.time()
        if cached is not None:
            cached_at, snapshot = cached
            if now_ts - cached_at <= self._ttl_seconds:
                log_event(
                    logger,
                    event="fundamental_market_data_cache_hit",
                    message="fundamental market data cache hit",
                    fields={"ticker": symbol},
                )
                return snapshot

        for attempt in range(self._max_retries + 1):
            try:
                snapshot = self._fetch_once(symbol)
                self._cache[symbol] = (now_ts, snapshot)
                return snapshot
            except Exception as exc:
                is_last_attempt = attempt >= self._max_retries
                log_event(
                    logger,
                    event="fundamental_market_data_fetch_failed",
                    message="fundamental market data fetch failed",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_MARKET_DATA_FETCH_FAILED",
                    fields={
                        "ticker": symbol,
                        "attempt": attempt + 1,
                        "max_attempts": self._max_retries + 1,
                        "exception": str(exc),
                    },
                )
                if is_last_attempt:
                    return self._fallback_snapshot(symbol, reason=str(exc))
                time.sleep(self._retry_delay_seconds * float(attempt + 1))

        return self._fallback_snapshot(symbol, reason="unreachable")

    def _fetch_once(self, ticker_symbol: str) -> MarketSnapshot:
        ticker_info = self._safe_info(ticker_symbol)
        tnx_info = self._safe_info("^TNX")

        current_price = self._pick_first_float(
            ticker_info, ("currentPrice", "regularMarketPrice", "previousClose")
        )
        market_cap = self._to_float(ticker_info.get("marketCap"))
        shares_outstanding = self._to_float(ticker_info.get("sharesOutstanding"))
        beta = self._to_float(ticker_info.get("beta"))
        if beta is None:
            beta = DEFAULT_BETA

        risk_free_raw = self._pick_first_float(
            tnx_info,
            ("regularMarketPrice", "previousClose", "currentPrice"),
        )
        risk_free_rate = self._normalize_rate(risk_free_raw)
        warnings: list[str] = []
        if risk_free_rate is None:
            risk_free_rate = DEFAULT_RISK_FREE_RATE
            warnings.append("risk_free_rate defaulted to 4.2%")

        consensus_growth_rate = self._pick_first_float(
            ticker_info,
            ("revenueGrowth", "earningsGrowth"),
        )
        target_mean_price = self._to_float(ticker_info.get("targetMeanPrice"))

        snapshot = MarketSnapshot(
            current_price=current_price,
            market_cap=market_cap,
            shares_outstanding=shares_outstanding,
            beta=beta,
            risk_free_rate=risk_free_rate,
            consensus_growth_rate=consensus_growth_rate,
            target_mean_price=target_mean_price,
            as_of=datetime.now(timezone.utc).isoformat(),
            provider="yfinance",
            missing_fields=self._missing_fields(
                current_price=current_price,
                market_cap=market_cap,
                shares_outstanding=shares_outstanding,
                beta=beta,
                risk_free_rate=risk_free_rate,
                consensus_growth_rate=consensus_growth_rate,
                target_mean_price=target_mean_price,
            ),
            source_warnings=tuple(warnings),
        )

        log_event(
            logger,
            event="fundamental_market_data_fetched",
            message="fundamental market data fetched",
            fields={
                "ticker": ticker_symbol,
                "provider": snapshot.provider,
                "missing_fields": list(snapshot.missing_fields),
            },
        )
        return snapshot

    def _safe_info(self, ticker_symbol: str) -> dict[str, object]:
        info = yf.Ticker(ticker_symbol).info
        if not isinstance(info, dict):
            return {}
        return cast(dict[str, object], info)

    @staticmethod
    def _to_float(value: object) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int | float):
            parsed = float(value)
            if parsed != parsed:
                return None
            return parsed
        if isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError:
                return None
            if parsed != parsed:
                return None
            return parsed
        return None

    @classmethod
    def _pick_first_float(
        cls,
        source: dict[str, object],
        keys: tuple[str, ...],
    ) -> float | None:
        for key in keys:
            parsed = cls._to_float(source.get(key))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _normalize_rate(value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            return None

        normalized = value
        if normalized > 1.0:
            normalized /= 100.0
        if normalized > 1.0:
            normalized /= 100.0

        if normalized <= 0:
            return None
        return normalized

    @staticmethod
    def _missing_fields(
        *,
        current_price: float | None,
        market_cap: float | None,
        shares_outstanding: float | None,
        beta: float | None,
        risk_free_rate: float | None,
        consensus_growth_rate: float | None,
        target_mean_price: float | None,
    ) -> tuple[str, ...]:
        missing: list[str] = []
        if current_price is None:
            missing.append("current_price")
        if market_cap is None:
            missing.append("market_cap")
        if shares_outstanding is None:
            missing.append("shares_outstanding")
        if beta is None:
            missing.append("beta")
        if risk_free_rate is None:
            missing.append("risk_free_rate")
        if consensus_growth_rate is None:
            missing.append("consensus_growth_rate")
        if target_mean_price is None:
            missing.append("target_mean_price")
        return tuple(missing)

    def _fallback_snapshot(self, ticker_symbol: str, *, reason: str) -> MarketSnapshot:
        log_event(
            logger,
            event="fundamental_market_data_fallback_used",
            message="fundamental market data fallback used",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_MARKET_DATA_FALLBACK",
            fields={"ticker": ticker_symbol, "reason": reason},
        )
        return MarketSnapshot(
            current_price=None,
            market_cap=None,
            shares_outstanding=None,
            beta=DEFAULT_BETA,
            risk_free_rate=DEFAULT_RISK_FREE_RATE,
            consensus_growth_rate=None,
            target_mean_price=None,
            as_of=datetime.now(timezone.utc).isoformat(),
            provider="yfinance",
            missing_fields=(
                "current_price",
                "market_cap",
                "shares_outstanding",
                "consensus_growth_rate",
                "target_mean_price",
            ),
            source_warnings=(f"market data fallback used: {reason}",),
        )


market_data_client = MarketDataClient()
