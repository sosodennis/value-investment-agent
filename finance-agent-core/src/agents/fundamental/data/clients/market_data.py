from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from src.agents.fundamental.data.clients.market_providers import (
    FREDMacroProvider,
    ProviderFetch,
    YahooFinanceProvider,
)
from src.agents.fundamental.data.ports import MarketDatum
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

DEFAULT_RISK_FREE_RATE = 0.042
DEFAULT_BETA = 1.0

MARKET_FIELDS: tuple[str, ...] = (
    "current_price",
    "market_cap",
    "shares_outstanding",
    "beta",
    "risk_free_rate",
    "consensus_growth_rate",
    "target_mean_price",
)

FIELD_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "risk_free_rate": ("fred", "yfinance"),
    "current_price": ("yfinance",),
    "market_cap": ("yfinance",),
    "shares_outstanding": ("yfinance",),
    "beta": ("yfinance",),
    "consensus_growth_rate": ("yfinance",),
    "target_mean_price": ("yfinance",),
}


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
    quality_flags: tuple[str, ...]
    license_note: str | None
    market_datums: dict[str, dict[str, object]]

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
            "quality_flags": list(self.quality_flags),
            "license_note": self.license_note,
            "market_datums": self.market_datums,
        }


class MarketDataClient:
    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.25,
        providers: tuple[object, ...] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._cache: dict[str, tuple[float, MarketSnapshot]] = {}
        configured = providers or (YahooFinanceProvider(), FREDMacroProvider())
        self._providers = tuple(cast(tuple[object, ...], configured))

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
        provider_results: dict[str, dict[str, MarketDatum]] = {}
        source_warnings: list[str] = []
        quality_flags: list[str] = []
        license_notes: list[str] = []

        for provider in self._providers:
            provider_name = _provider_name(provider)
            try:
                fetched = _provider_fetch(provider, ticker_symbol)
            except Exception as exc:
                source_warnings.append(f"{provider_name} fetch failed: {exc}")
                continue

            provider_results[provider_name] = fetched.datums
            source_warnings.extend(fetched.warnings)
            provider_license_note = _provider_license(provider)
            if provider_license_note:
                license_notes.append(provider_license_note)

        selected_datums: dict[str, MarketDatum] = {}
        for field in MARKET_FIELDS:
            selected_datums[field] = self._select_datum(
                field=field,
                provider_results=provider_results,
            )
            quality_flags.extend(
                f"{field}:{flag}" for flag in selected_datums[field].quality_flags
            )

        if selected_datums["beta"].value is None:
            selected_datums["beta"] = MarketDatum(
                value=DEFAULT_BETA,
                source="policy_default",
                as_of=datetime.now(timezone.utc).isoformat(),
                quality_flags=("defaulted",),
                license_note="Internal default policy",
            )
            source_warnings.append("beta defaulted to 1.0")
            quality_flags.append("beta:defaulted")

        if selected_datums["risk_free_rate"].value is None:
            selected_datums["risk_free_rate"] = MarketDatum(
                value=DEFAULT_RISK_FREE_RATE,
                source="policy_default",
                as_of=datetime.now(timezone.utc).isoformat(),
                quality_flags=("defaulted",),
                license_note="Internal default policy",
            )
            source_warnings.append("risk_free_rate defaulted to 4.2%")
            quality_flags.append("risk_free_rate:defaulted")

        primary_provider = selected_datums["current_price"].source
        if not primary_provider or primary_provider == "unavailable":
            primary_provider = "market_data"

        as_of = selected_datums["current_price"].as_of
        if as_of is None:
            as_of = selected_datums["risk_free_rate"].as_of
        if as_of is None:
            as_of = datetime.now(timezone.utc).isoformat()

        missing_fields = tuple(
            field for field in MARKET_FIELDS if selected_datums[field].value is None
        )

        market_datums = {
            field: datum.to_mapping() for field, datum in selected_datums.items()
        }
        merged_license_note = (
            "; ".join(dict.fromkeys(note for note in license_notes if note)) or None
        )
        dedup_quality_flags = tuple(
            dict.fromkeys(flag for flag in quality_flags if flag)
        )
        dedup_warnings = tuple(dict.fromkeys(msg for msg in source_warnings if msg))

        snapshot = MarketSnapshot(
            current_price=selected_datums["current_price"].value,
            market_cap=selected_datums["market_cap"].value,
            shares_outstanding=selected_datums["shares_outstanding"].value,
            beta=selected_datums["beta"].value,
            risk_free_rate=selected_datums["risk_free_rate"].value,
            consensus_growth_rate=selected_datums["consensus_growth_rate"].value,
            target_mean_price=selected_datums["target_mean_price"].value,
            as_of=as_of,
            provider=primary_provider,
            missing_fields=missing_fields,
            source_warnings=dedup_warnings,
            quality_flags=dedup_quality_flags,
            license_note=merged_license_note,
            market_datums=market_datums,
        )

        log_event(
            logger,
            event="fundamental_market_data_fetched",
            message="fundamental market data fetched",
            fields={
                "ticker": ticker_symbol,
                "provider": snapshot.provider,
                "missing_fields": list(snapshot.missing_fields),
                "quality_flags": list(snapshot.quality_flags),
            },
        )
        return snapshot

    def _select_datum(
        self,
        *,
        field: str,
        provider_results: dict[str, dict[str, MarketDatum]],
    ) -> MarketDatum:
        preferred = FIELD_SOURCE_PRIORITY.get(field, ())
        if not preferred:
            preferred = tuple(provider_results.keys())

        first_present: MarketDatum | None = None
        for provider_name in preferred:
            datums = provider_results.get(provider_name)
            if not datums:
                continue
            datum = datums.get(field)
            if datum is None:
                continue
            if first_present is None:
                first_present = datum
            if datum.value is not None:
                return datum

        if first_present is not None:
            return first_present

        return MarketDatum(
            value=None,
            source="unavailable",
            as_of=datetime.now(timezone.utc).isoformat(),
            quality_flags=("missing",),
            license_note=None,
        )

    def _fallback_snapshot(self, ticker_symbol: str, *, reason: str) -> MarketSnapshot:
        log_event(
            logger,
            event="fundamental_market_data_fallback_used",
            message="fundamental market data fallback used",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_MARKET_DATA_FALLBACK",
            fields={"ticker": ticker_symbol, "reason": reason},
        )
        now = datetime.now(timezone.utc).isoformat()
        beta = MarketDatum(
            value=DEFAULT_BETA,
            source="policy_default",
            as_of=now,
            quality_flags=("defaulted",),
            license_note="Internal default policy",
        )
        risk_free = MarketDatum(
            value=DEFAULT_RISK_FREE_RATE,
            source="policy_default",
            as_of=now,
            quality_flags=("defaulted",),
            license_note="Internal default policy",
        )
        unavailable = MarketDatum(
            value=None,
            source="unavailable",
            as_of=now,
            quality_flags=("missing", "fallback"),
            license_note=None,
        )
        market_datums = {
            "current_price": unavailable.to_mapping(),
            "market_cap": unavailable.to_mapping(),
            "shares_outstanding": unavailable.to_mapping(),
            "beta": beta.to_mapping(),
            "risk_free_rate": risk_free.to_mapping(),
            "consensus_growth_rate": unavailable.to_mapping(),
            "target_mean_price": unavailable.to_mapping(),
        }
        return MarketSnapshot(
            current_price=None,
            market_cap=None,
            shares_outstanding=None,
            beta=DEFAULT_BETA,
            risk_free_rate=DEFAULT_RISK_FREE_RATE,
            consensus_growth_rate=None,
            target_mean_price=None,
            as_of=now,
            provider="market_data",
            missing_fields=(
                "current_price",
                "market_cap",
                "shares_outstanding",
                "consensus_growth_rate",
                "target_mean_price",
            ),
            source_warnings=(f"market data fallback used: {reason}",),
            quality_flags=(
                "current_price:missing",
                "market_cap:missing",
                "shares_outstanding:missing",
                "consensus_growth_rate:missing",
                "target_mean_price:missing",
                "beta:defaulted",
                "risk_free_rate:defaulted",
            ),
            license_note="Internal default policy",
            market_datums=market_datums,
        )


def _provider_name(provider: object) -> str:
    raw = getattr(provider, "name", None)
    if isinstance(raw, str) and raw:
        return raw
    return provider.__class__.__name__.lower()


def _provider_license(provider: object) -> str | None:
    raw = getattr(provider, "license_note", None)
    if isinstance(raw, str) and raw:
        return raw
    return None


def _provider_fetch(provider: object, ticker_symbol: str) -> ProviderFetch:
    fetch = getattr(provider, "fetch", None)
    if callable(fetch):
        try:
            result = fetch(ticker_symbol)
        except TypeError:
            result = fetch()
        if isinstance(result, ProviderFetch):
            return result
    fetch_datums = getattr(provider, "fetch_datums", None)
    if callable(fetch_datums):
        datums = fetch_datums(ticker_symbol)
        if isinstance(datums, dict):
            normalized = {
                key: value
                for key, value in datums.items()
                if isinstance(key, str) and isinstance(value, MarketDatum)
            }
            return ProviderFetch(datums=normalized)
    raise TypeError(f"provider {_provider_name(provider)} has no valid fetch API")


market_data_client = MarketDataClient()
