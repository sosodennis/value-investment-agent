from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import yfinance as yf

from ..domain.provider_contracts import (
    MarketDataProvider,
    MarketDatum,
    ProviderFetch,
)


class YahooFinanceProvider(MarketDataProvider):
    name = "yfinance"
    license_note = (
        "Yahoo Finance data via yfinance. Verify commercial licensing/terms before "
        "production redistribution."
    )

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        ticker_info = self._safe_info(ticker_symbol)
        tnx_info = self._safe_info("^TNX")
        as_of = datetime.now(timezone.utc).isoformat()

        current_price = self._pick_first_float(
            ticker_info, ("currentPrice", "regularMarketPrice", "previousClose")
        )
        market_cap = self._to_float(ticker_info.get("marketCap"))
        shares_outstanding = self._to_float(ticker_info.get("sharesOutstanding"))
        beta = self._to_float(ticker_info.get("beta"))
        consensus_growth_rate = self._pick_first_float(
            ticker_info,
            ("revenueGrowth", "earningsGrowth"),
        )
        target_mean_price = self._to_float(ticker_info.get("targetMeanPrice"))
        risk_free_raw = self._pick_first_float(
            tnx_info,
            ("regularMarketPrice", "previousClose", "currentPrice"),
        )
        risk_free_rate = self._normalize_rate(risk_free_raw)

        datums = {
            "current_price": self._datum("current_price", current_price, as_of=as_of),
            "market_cap": self._datum("market_cap", market_cap, as_of=as_of),
            "shares_outstanding": self._datum(
                "shares_outstanding", shares_outstanding, as_of=as_of
            ),
            "beta": self._datum("beta", beta, as_of=as_of),
            "risk_free_rate": self._datum(
                "risk_free_rate", risk_free_rate, as_of=as_of
            ),
            "consensus_growth_rate": self._datum(
                "consensus_growth_rate",
                consensus_growth_rate,
                as_of=as_of,
                horizon="short_term",
                source_detail="yfinance:revenueGrowth|earningsGrowth",
            ),
            "target_mean_price": self._datum(
                "target_mean_price", target_mean_price, as_of=as_of
            ),
        }
        return ProviderFetch(datums=datums)

    def _datum(
        self,
        field: str,
        value: float | None,
        *,
        as_of: str,
        horizon: str | None = None,
        source_detail: str | None = None,
    ) -> MarketDatum:
        del field
        quality_flags: tuple[str, ...] = ("missing",) if value is None else ()
        return MarketDatum(
            value=value,
            source=self.name,
            as_of=as_of,
            horizon=horizon,
            source_detail=source_detail,
            quality_flags=quality_flags,
            license_note=self.license_note,
        )

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
