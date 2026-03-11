from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from ..application.ports import MarketDataProvider, ProviderFetch
from ..domain.market_datum import MarketDatum

DEFAULT_HTTP_TIMEOUT_SECONDS = 4.0
FRED_10Y_SERIES_ID = "DGS10"
FRED_LONG_RUN_GROWTH_SERIES_ID = "A191RL1Q225SBEA"
FRED_10Y_UPDATE_CADENCE_DAYS = 1
FRED_LONG_RUN_GROWTH_UPDATE_CADENCE_DAYS = 90


class FredMacroProvider(MarketDataProvider):
    name = "fred"
    license_note = "FRED series data from Federal Reserve Bank of St. Louis."

    def __init__(
        self,
        *,
        api_key: str | None = None,
        risk_free_series_id: str = FRED_10Y_SERIES_ID,
        long_run_growth_series_id: str = FRED_LONG_RUN_GROWTH_SERIES_ID,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("FRED_API_KEY")
        self._risk_free_series_id = risk_free_series_id
        self._long_run_growth_series_id = long_run_growth_series_id
        self._timeout_seconds = timeout_seconds

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        del ticker_symbol
        risk_free_datum, risk_free_warnings = self._fetch_series_datum(
            series_id=self._risk_free_series_id,
            parser=self._parse_rate,
            invalid_flag="invalid_rate",
            invalid_warning="fred risk_free_rate invalid",
            horizon="long_term",
            update_cadence_days=FRED_10Y_UPDATE_CADENCE_DAYS,
            source_detail=f"fred:{self._risk_free_series_id}",
        )
        long_run_growth_datum, long_run_warnings = self._fetch_series_datum(
            series_id=self._long_run_growth_series_id,
            parser=self._parse_growth_anchor,
            invalid_flag="invalid_growth_anchor",
            invalid_warning="fred long_run_growth_anchor invalid",
            horizon="long_term",
            update_cadence_days=FRED_LONG_RUN_GROWTH_UPDATE_CADENCE_DAYS,
            source_detail=f"fred:{self._long_run_growth_series_id}",
        )
        warnings = tuple(
            list(risk_free_warnings) + list(long_run_warnings),
        )
        return ProviderFetch(
            datums={
                "risk_free_rate": risk_free_datum,
                "long_run_growth_anchor": long_run_growth_datum,
            },
            warnings=warnings,
        )

    def _fetch_series_datum(
        self,
        *,
        series_id: str,
        parser: Callable[[object], float | None],
        invalid_flag: str,
        invalid_warning: str,
        horizon: str,
        update_cadence_days: int,
        source_detail: str,
    ) -> tuple[MarketDatum, tuple[str, ...]]:
        as_of = datetime.now(timezone.utc).isoformat()
        if not self._api_key:
            return (
                MarketDatum(
                    value=None,
                    source=self.name,
                    as_of=as_of,
                    horizon=horizon,
                    update_cadence_days=update_cadence_days,
                    source_detail=source_detail,
                    quality_flags=("missing_api_key",),
                    license_note=self.license_note,
                ),
                ("fred api key missing",),
            )

        query = urlencode(
            {
                "series_id": series_id,
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
            return (
                MarketDatum(
                    value=None,
                    source=self.name,
                    as_of=as_of,
                    horizon=horizon,
                    update_cadence_days=update_cadence_days,
                    source_detail=source_detail,
                    quality_flags=("fetch_error",),
                    license_note=self.license_note,
                ),
                (f"fred fetch failed for {series_id}: {exc}",),
            )

        observations_raw = payload.get("observations")
        if not isinstance(observations_raw, list) or not observations_raw:
            return (
                MarketDatum(
                    value=None,
                    source=self.name,
                    as_of=as_of,
                    horizon=horizon,
                    update_cadence_days=update_cadence_days,
                    source_detail=source_detail,
                    quality_flags=("missing_observation",),
                    license_note=self.license_note,
                ),
                (f"fred observations missing for {series_id}",),
            )

        first = observations_raw[0]
        if not isinstance(first, dict):
            return (
                MarketDatum(
                    value=None,
                    source=self.name,
                    as_of=as_of,
                    horizon=horizon,
                    update_cadence_days=update_cadence_days,
                    source_detail=source_detail,
                    quality_flags=("invalid_observation",),
                    license_note=self.license_note,
                ),
                (f"fred observation invalid for {series_id}",),
            )

        raw_value = first.get("value")
        observation_date = first.get("date")
        value_as_of = (
            str(observation_date)
            if isinstance(observation_date, str) and observation_date
            else as_of
        )
        parsed_value = parser(raw_value)
        if parsed_value is None:
            return (
                MarketDatum(
                    value=None,
                    source=self.name,
                    as_of=value_as_of,
                    horizon=horizon,
                    update_cadence_days=update_cadence_days,
                    source_detail=source_detail,
                    quality_flags=(invalid_flag,),
                    license_note=self.license_note,
                ),
                (invalid_warning,),
            )

        return (
            MarketDatum(
                value=parsed_value,
                source=self.name,
                as_of=value_as_of,
                horizon=horizon,
                update_cadence_days=update_cadence_days,
                source_detail=source_detail,
                quality_flags=(),
                license_note=self.license_note,
            ),
            (),
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

    @staticmethod
    def _parse_growth_anchor(raw_value: object) -> float | None:
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

        if value > 1.0:
            value /= 100.0
        if value < -0.5 or value > 0.5:
            return None
        return value
