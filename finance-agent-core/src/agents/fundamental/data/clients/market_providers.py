from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import yfinance as yf

from src.agents.fundamental.data.ports import MarketDataProvider, MarketDatum

DEFAULT_HTTP_TIMEOUT_SECONDS = 4.0
FRED_10Y_SERIES_ID = "DGS10"


@dataclass(frozen=True)
class ProviderFetch:
    datums: dict[str, MarketDatum]
    warnings: tuple[str, ...] = ()


class YahooFinanceProvider(MarketDataProvider):
    name = "yfinance"
    license_note = (
        "Yahoo Finance data via yfinance. Verify commercial licensing/terms before "
        "production redistribution."
    )

    def fetch_datums(self, ticker_symbol: str) -> dict[str, MarketDatum]:
        result = self.fetch(ticker_symbol)
        return result.datums

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
                "consensus_growth_rate", consensus_growth_rate, as_of=as_of
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
    ) -> MarketDatum:
        quality_flags: tuple[str, ...] = ("missing",) if value is None else ()
        return MarketDatum(
            value=value,
            source=self.name,
            as_of=as_of,
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


class FREDMacroProvider(MarketDataProvider):
    name = "fred"
    license_note = "FRED series data from Federal Reserve Bank of St. Louis."

    def __init__(
        self,
        *,
        api_key: str | None = None,
        series_id: str = FRED_10Y_SERIES_ID,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("FRED_API_KEY")
        self._series_id = series_id
        self._timeout_seconds = timeout_seconds

    def fetch_datums(self, ticker_symbol: str) -> dict[str, MarketDatum]:
        del ticker_symbol
        return self.fetch().datums

    def fetch(self) -> ProviderFetch:
        as_of = datetime.now(timezone.utc).isoformat()
        if not self._api_key:
            return ProviderFetch(
                datums={
                    "risk_free_rate": MarketDatum(
                        value=None,
                        source=self.name,
                        as_of=as_of,
                        quality_flags=("missing_api_key",),
                        license_note=self.license_note,
                    )
                },
                warnings=("fred api key missing",),
            )

        query = urlencode(
            {
                "series_id": self._series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            }
        )
        url = "https://api.stlouisfed.org/fred/series/observations" f"?{query}"
        try:
            with urlopen(url, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return ProviderFetch(
                datums={
                    "risk_free_rate": MarketDatum(
                        value=None,
                        source=self.name,
                        as_of=as_of,
                        quality_flags=("fetch_error",),
                        license_note=self.license_note,
                    )
                },
                warnings=(f"fred fetch failed: {exc}",),
            )

        observations_raw = payload.get("observations")
        if not isinstance(observations_raw, list) or not observations_raw:
            return ProviderFetch(
                datums={
                    "risk_free_rate": MarketDatum(
                        value=None,
                        source=self.name,
                        as_of=as_of,
                        quality_flags=("missing_observation",),
                        license_note=self.license_note,
                    )
                },
                warnings=("fred observations missing",),
            )

        first = observations_raw[0]
        if not isinstance(first, dict):
            return ProviderFetch(
                datums={
                    "risk_free_rate": MarketDatum(
                        value=None,
                        source=self.name,
                        as_of=as_of,
                        quality_flags=("invalid_observation",),
                        license_note=self.license_note,
                    )
                },
                warnings=("fred observation invalid",),
            )

        raw_value = first.get("value")
        observation_date = first.get("date")
        rate = self._parse_rate(raw_value)
        value_as_of = (
            str(observation_date)
            if isinstance(observation_date, str) and observation_date
            else as_of
        )

        if rate is None:
            return ProviderFetch(
                datums={
                    "risk_free_rate": MarketDatum(
                        value=None,
                        source=self.name,
                        as_of=value_as_of,
                        quality_flags=("invalid_rate",),
                        license_note=self.license_note,
                    )
                },
                warnings=("fred rate invalid",),
            )

        return ProviderFetch(
            datums={
                "risk_free_rate": MarketDatum(
                    value=rate,
                    source=self.name,
                    as_of=value_as_of,
                    quality_flags=(),
                    license_note=self.license_note,
                )
            }
        )

    @staticmethod
    def _parse_rate(raw_value: object) -> float | None:
        if isinstance(raw_value, str):
            if raw_value in {"", "."}:
                return None
            try:
                value = float(raw_value)
            except ValueError:
                return None
        elif isinstance(raw_value, int | float):
            value = float(raw_value)
        else:
            return None

        if value <= 0:
            return None
        if value > 1.0:
            value /= 100.0
        if value <= 0:
            return None
        return value
