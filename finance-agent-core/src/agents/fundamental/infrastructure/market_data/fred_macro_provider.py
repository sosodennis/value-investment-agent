from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .provider_contracts import (
    MarketDataProvider,
    MarketDatum,
    ProviderFetch,
)

DEFAULT_HTTP_TIMEOUT_SECONDS = 4.0
FRED_10Y_SERIES_ID = "DGS10"


class FredMacroProvider(MarketDataProvider):
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
        return self.fetch(ticker_symbol).datums

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        del ticker_symbol
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
