from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

from .consensus_anchor_aggregator import (
    FREE_CONSENSUS_AGGREGATE_SOURCE,
    build_target_consensus_anchor_datums,
)
from .fred_macro_provider import FredMacroProvider
from .free_consensus_governance import governance_warning_for_provider
from .investing_provider import InvestingProvider
from .marketbeat_provider import MarketBeatProvider
from .provider_contracts import (
    MarketDataProvider,
    MarketDatum,
)
from .tipranks_provider import TipRanksProvider
from .yahoo_finance_provider import YahooFinanceProvider

logger = get_logger(__name__)

DEFAULT_RISK_FREE_RATE = 0.042
DEFAULT_BETA = 1.0
DEFAULT_MARKET_STALE_MAX_DAYS = 5
DEFAULT_LONG_RUN_GROWTH_STALE_MAX_DAYS = 90
CANONICAL_TARGET_MEAN_HORIZON = "12m"
CANONICAL_SHARES_SCOPE_UNKNOWN = "unknown"

MARKET_FIELDS: tuple[str, ...] = (
    "current_price",
    "market_cap",
    "shares_outstanding",
    "beta",
    "risk_free_rate",
    "consensus_growth_rate",
    "long_run_growth_anchor",
    "target_mean_price",
)

FIELD_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "risk_free_rate": ("fred", "yfinance"),
    "current_price": ("yfinance",),
    "market_cap": ("yfinance",),
    "shares_outstanding": ("yfinance",),
    "beta": ("yfinance",),
    "consensus_growth_rate": ("yfinance",),
    "long_run_growth_anchor": ("fred",),
    "target_mean_price": (FREE_CONSENSUS_AGGREGATE_SOURCE, "yfinance"),
}


@dataclass(frozen=True)
class MarketSnapshot:
    current_price: float | None
    market_cap: float | None
    shares_outstanding: float | None
    beta: float | None
    risk_free_rate: float | None
    consensus_growth_rate: float | None
    long_run_growth_anchor: float | None
    target_mean_price: float | None
    market_stale_max_days: int
    shares_outstanding_is_stale: bool | None
    shares_outstanding_staleness_days: int | None
    as_of: str
    provider: str
    missing_fields: tuple[str, ...]
    source_warnings: tuple[str, ...]
    quality_flags: tuple[str, ...]
    license_note: str | None
    market_datums: dict[str, JSONObject]
    target_consensus_applied: bool = False
    target_consensus_source_count: int | None = None
    target_consensus_sources: tuple[str, ...] = ()
    target_consensus_fallback_reason: str | None = None
    target_consensus_warnings: tuple[str, ...] = ()
    target_consensus_warning_codes: tuple[str, ...] = ()
    target_consensus_quality_bucket: str | None = None
    target_consensus_confidence_weight: float | None = None

    def to_mapping(self) -> JSONObject:
        return {
            "current_price": self.current_price,
            "market_cap": self.market_cap,
            "shares_outstanding": self.shares_outstanding,
            "beta": self.beta,
            "risk_free_rate": self.risk_free_rate,
            "consensus_growth_rate": self.consensus_growth_rate,
            "long_run_growth_anchor": self.long_run_growth_anchor,
            "target_mean_price": self.target_mean_price,
            "market_stale_max_days": self.market_stale_max_days,
            "shares_outstanding_is_stale": self.shares_outstanding_is_stale,
            "shares_outstanding_staleness_days": self.shares_outstanding_staleness_days,
            "as_of": self.as_of,
            "provider": self.provider,
            "missing_fields": list(self.missing_fields),
            "source_warnings": list(self.source_warnings),
            "quality_flags": list(self.quality_flags),
            "target_consensus_applied": self.target_consensus_applied,
            "target_consensus_source_count": self.target_consensus_source_count,
            "target_consensus_sources": list(self.target_consensus_sources),
            "target_consensus_fallback_reason": self.target_consensus_fallback_reason,
            "target_consensus_warnings": list(self.target_consensus_warnings),
            "target_consensus_warning_codes": list(self.target_consensus_warning_codes),
            "target_consensus_quality_bucket": self.target_consensus_quality_bucket,
            "target_consensus_confidence_weight": self.target_consensus_confidence_weight,
            "license_note": self.license_note,
            "market_datums": self.market_datums,
        }


class MarketDataService:
    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.25,
        providers: tuple[MarketDataProvider, ...] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._cache: dict[str, tuple[float, MarketSnapshot]] = {}
        configured = providers or (
            YahooFinanceProvider(),
            FredMacroProvider(),
            TipRanksProvider(),
            InvestingProvider(),
            MarketBeatProvider(),
        )
        self._providers = tuple(configured)

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
        license_notes: list[str] = []
        free_target_consensus_enabled = _free_target_consensus_enabled()

        for provider in self._providers:
            provider_name = _provider_name(provider)
            try:
                fetched = provider.fetch(ticker_symbol)
            except Exception as exc:
                source_warnings.append(f"{provider_name} fetch failed: {exc}")
                governance_warning = _build_provider_governance_warning(
                    provider_name=provider_name,
                    exc=exc,
                )
                if governance_warning is not None:
                    source_warnings.append(governance_warning)
                continue

            provider_results[provider_name] = fetched.datums
            source_warnings.extend(fetched.warnings)
            provider_license_note = _provider_license(provider)
            if provider_license_note:
                license_notes.append(provider_license_note)

        if free_target_consensus_enabled:
            consensus_result = build_target_consensus_anchor_datums(
                provider_results=provider_results,
                now=datetime.now(timezone.utc),
            )
            source_warnings.extend(consensus_result.warnings)
            if consensus_result.datums:
                provider_results[FREE_CONSENSUS_AGGREGATE_SOURCE] = (
                    consensus_result.datums
                )
                aggregate_license = consensus_result.datums[
                    "target_mean_price"
                ].license_note
                if aggregate_license:
                    license_notes.append(aggregate_license)

        selected_datums: dict[str, MarketDatum] = {}
        for field in MARKET_FIELDS:
            selected_datums[field] = self._select_datum(
                field=field,
                provider_results=provider_results,
            )
        selected_datums, contract_warnings = _enforce_market_datum_contract(
            datums=selected_datums
        )
        source_warnings.extend(contract_warnings)

        if selected_datums["beta"].value is None:
            selected_datums["beta"] = MarketDatum(
                value=DEFAULT_BETA,
                source="policy_default",
                as_of=datetime.now(timezone.utc).isoformat(),
                quality_flags=("defaulted",),
                license_note="Internal default policy",
            )
            source_warnings.append("beta defaulted to 1.0")

        if selected_datums["risk_free_rate"].value is None:
            selected_datums["risk_free_rate"] = MarketDatum(
                value=DEFAULT_RISK_FREE_RATE,
                source="policy_default",
                as_of=datetime.now(timezone.utc).isoformat(),
                quality_flags=("defaulted",),
                license_note="Internal default policy",
            )
            source_warnings.append("risk_free_rate defaulted to 4.2%")

        dedup_warnings = tuple(dict.fromkeys(msg for msg in source_warnings if msg))
        (
            target_consensus_applied,
            target_consensus_source_count,
            target_consensus_sources,
            target_consensus_fallback_reason,
            target_consensus_warnings,
            target_consensus_warning_codes,
            target_consensus_quality_bucket,
            target_consensus_confidence_weight,
        ) = _resolve_target_consensus_diagnostics(
            target_mean_datum=selected_datums["target_mean_price"],
            source_warnings=dedup_warnings,
            free_target_consensus_enabled=free_target_consensus_enabled,
        )
        if target_consensus_fallback_reason is not None:
            target_datum = selected_datums["target_mean_price"]
            target_quality_flags = list(target_datum.quality_flags)
            target_quality_flags.append("consensus_fallback")
            selected_datums["target_mean_price"] = replace(
                target_datum,
                fallback_reason=target_consensus_fallback_reason,
                quality_flags=tuple(
                    dict.fromkeys(flag for flag in target_quality_flags if flag)
                ),
            )

        stale_max_days = _market_stale_max_days()
        selected_datums = _attach_staleness(
            datums=selected_datums,
            stale_max_days=stale_max_days,
            now=datetime.now(timezone.utc),
        )
        quality_flags: list[str] = []
        for field, datum in selected_datums.items():
            quality_flags.extend(f"{field}:{flag}" for flag in datum.quality_flags)

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
        shares_staleness = _extract_staleness(selected_datums["shares_outstanding"])

        snapshot = MarketSnapshot(
            current_price=selected_datums["current_price"].value,
            market_cap=selected_datums["market_cap"].value,
            shares_outstanding=selected_datums["shares_outstanding"].value,
            beta=selected_datums["beta"].value,
            risk_free_rate=selected_datums["risk_free_rate"].value,
            consensus_growth_rate=selected_datums["consensus_growth_rate"].value,
            long_run_growth_anchor=selected_datums["long_run_growth_anchor"].value,
            target_mean_price=selected_datums["target_mean_price"].value,
            market_stale_max_days=stale_max_days,
            shares_outstanding_is_stale=shares_staleness[0],
            shares_outstanding_staleness_days=shares_staleness[1],
            as_of=as_of,
            provider=primary_provider,
            missing_fields=missing_fields,
            source_warnings=dedup_warnings,
            quality_flags=dedup_quality_flags,
            target_consensus_applied=target_consensus_applied,
            target_consensus_source_count=target_consensus_source_count,
            target_consensus_sources=target_consensus_sources,
            target_consensus_fallback_reason=target_consensus_fallback_reason,
            target_consensus_warnings=target_consensus_warnings,
            target_consensus_warning_codes=target_consensus_warning_codes,
            target_consensus_quality_bucket=target_consensus_quality_bucket,
            target_consensus_confidence_weight=target_consensus_confidence_weight,
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
                "source_warnings": list(snapshot.source_warnings),
                "target_consensus_applied": snapshot.target_consensus_applied,
                "target_consensus_source_count": snapshot.target_consensus_source_count,
                "target_consensus_sources": list(snapshot.target_consensus_sources),
                "target_consensus_fallback_reason": snapshot.target_consensus_fallback_reason,
                "target_consensus_warnings": list(snapshot.target_consensus_warnings),
                "target_consensus_warning_codes": list(
                    snapshot.target_consensus_warning_codes
                ),
                "target_consensus_quality_bucket": snapshot.target_consensus_quality_bucket,
                "target_consensus_confidence_weight": snapshot.target_consensus_confidence_weight,
                "key_market_inputs": _build_key_market_input_log_fields(
                    selected_datums
                ),
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
            "long_run_growth_anchor": unavailable.to_mapping(),
            "target_mean_price": unavailable.to_mapping(),
        }
        return MarketSnapshot(
            current_price=None,
            market_cap=None,
            shares_outstanding=None,
            beta=DEFAULT_BETA,
            risk_free_rate=DEFAULT_RISK_FREE_RATE,
            consensus_growth_rate=None,
            long_run_growth_anchor=None,
            target_mean_price=None,
            market_stale_max_days=_market_stale_max_days(),
            shares_outstanding_is_stale=None,
            shares_outstanding_staleness_days=None,
            as_of=now,
            provider="market_data",
            missing_fields=(
                "current_price",
                "market_cap",
                "shares_outstanding",
                "consensus_growth_rate",
                "long_run_growth_anchor",
                "target_mean_price",
            ),
            source_warnings=(f"market data fallback used: {reason}",),
            quality_flags=(
                "current_price:missing",
                "market_cap:missing",
                "shares_outstanding:missing",
                "consensus_growth_rate:missing",
                "long_run_growth_anchor:missing",
                "target_mean_price:missing",
                "beta:defaulted",
                "risk_free_rate:defaulted",
            ),
            target_consensus_applied=False,
            target_consensus_source_count=None,
            target_consensus_sources=(),
            target_consensus_fallback_reason="market_data_fallback",
            target_consensus_warnings=(),
            target_consensus_warning_codes=("market_data_fallback",),
            target_consensus_quality_bucket="degraded",
            target_consensus_confidence_weight=0.0,
            license_note="Internal default policy",
            market_datums=market_datums,
        )


def _resolve_target_consensus_diagnostics(
    *,
    target_mean_datum: MarketDatum,
    source_warnings: tuple[str, ...],
    free_target_consensus_enabled: bool,
) -> tuple[
    bool,
    int | None,
    tuple[str, ...],
    str | None,
    tuple[str, ...],
    tuple[str, ...],
    str | None,
    float | None,
]:
    applied = (
        target_mean_datum.source == FREE_CONSENSUS_AGGREGATE_SOURCE
        and target_mean_datum.value is not None
    )
    source_count, sources = _parse_target_consensus_source_detail(
        target_mean_datum.source_detail
    )
    consensus_warnings_list = list(_filter_target_consensus_warnings(source_warnings))
    fallback_reason: str | None = None
    if (
        free_target_consensus_enabled
        and not applied
        and target_mean_datum.source == "yfinance"
        and target_mean_datum.value is not None
    ):
        fallback_reason = _classify_target_consensus_fallback(
            tuple(consensus_warnings_list)
        )
    if isinstance(source_count, int) and source_count <= 1:
        fallback_reason = "single_source_consensus"
        consensus_warnings_list.append(
            "target consensus degraded: single_source_consensus source_count=1"
        )
    consensus_warnings = tuple(dict.fromkeys(consensus_warnings_list))
    consensus_warning_codes = _extract_target_consensus_warning_codes(
        warnings=consensus_warnings,
        fallback_reason=fallback_reason,
    )
    quality_bucket, confidence_weight = _resolve_target_consensus_quality(
        applied=applied,
        source_count=source_count,
        fallback_reason=fallback_reason,
        target_mean_available=target_mean_datum.value is not None,
    )
    return (
        applied,
        source_count,
        sources,
        fallback_reason,
        consensus_warnings,
        consensus_warning_codes,
        quality_bucket,
        confidence_weight,
    )


def _resolve_target_consensus_quality(
    *,
    applied: bool,
    source_count: int | None,
    fallback_reason: str | None,
    target_mean_available: bool,
) -> tuple[str | None, float | None]:
    if not target_mean_available:
        return "degraded", 0.0
    if isinstance(source_count, int) and source_count <= 1:
        return "degraded", 0.30
    if applied and isinstance(source_count, int) and source_count >= 3:
        return "high", 1.0
    if applied and isinstance(source_count, int) and source_count >= 2:
        return "medium", 0.75
    if isinstance(source_count, int) and source_count >= 2:
        return "medium", 0.75
    return "degraded", 0.30


def _classify_target_consensus_fallback(
    consensus_warnings: tuple[str, ...],
) -> str:
    if any("code=provider_blocked_http" in warning for warning in consensus_warnings):
        return "provider_blocked"
    if any("code=provider_rate_limited" in warning for warning in consensus_warnings):
        return "provider_rate_limited"
    if any(
        "code=provider_dns_error" in warning
        or "code=provider_connection_error" in warning
        for warning in consensus_warnings
    ):
        return "provider_network_error"
    if any("insufficient_sources=" in warning for warning in consensus_warnings):
        return "insufficient_sources"
    if any(
        "code=" in warning and "_target_mean_missing" in warning
        for warning in consensus_warnings
    ):
        return "provider_parse_missing"
    if any("parse missing" in warning for warning in consensus_warnings):
        return "provider_parse_missing"
    if any("fetch failed:" in warning for warning in consensus_warnings):
        return "provider_fetch_failed"
    return "aggregate_unavailable"


def _filter_target_consensus_warnings(
    source_warnings: tuple[str, ...],
) -> tuple[str, ...]:
    relevant_tokens = (
        "target consensus aggregate",
        "target_mean_price",
        "tipranks ",
        "investing ",
        "marketbeat ",
        "provider_governance_review_required",
    )
    return tuple(
        warning
        for warning in source_warnings
        if any(token in warning for token in relevant_tokens)
    )


def _extract_target_consensus_warning_codes(
    *,
    warnings: tuple[str, ...],
    fallback_reason: str | None,
) -> tuple[str, ...]:
    codes: list[str] = []
    if isinstance(fallback_reason, str) and fallback_reason:
        codes.append(fallback_reason)
    for warning in warnings:
        explicit_code = _extract_warning_code_token(warning)
        if explicit_code is not None:
            codes.append(explicit_code)
        if "insufficient_sources=" in warning:
            codes.append("insufficient_sources")
        if "single_source_consensus" in warning:
            codes.append("single_source_consensus")
        if "provider_governance_review_required" in warning:
            codes.append("provider_governance_review_required")
        if "parse missing" in warning or "_target_mean_missing" in warning:
            codes.append("provider_parse_missing")
        if "fetch failed:" in warning:
            codes.append("provider_fetch_failed")
    return tuple(dict.fromkeys(code for code in codes if code))


def _extract_warning_code_token(warning: str) -> str | None:
    marker = "code="
    start = warning.find(marker)
    if start < 0:
        return None
    token_start = start + len(marker)
    token_chars: list[str] = []
    for char in warning[token_start:]:
        if char.isalnum() or char in {"_", "-", "."}:
            token_chars.append(char)
            continue
        break
    if not token_chars:
        return None
    return "".join(token_chars)


def _parse_target_consensus_source_detail(
    source_detail: str | None,
) -> tuple[int | None, tuple[str, ...]]:
    if not isinstance(source_detail, str) or not source_detail.strip():
        return None, ()
    key_values = _parse_semicolon_key_values(source_detail)
    source_count = _parse_optional_int(key_values.get("source_count"))
    raw_sources = key_values.get("sources")
    if not isinstance(raw_sources, str) or not raw_sources:
        return source_count, ()
    sources = tuple(
        dict.fromkeys(item.strip() for item in raw_sources.split(",") if item.strip())
    )
    return source_count, sources


def _parse_semicolon_key_values(raw: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for segment in raw.split(";"):
        key, sep, value = segment.partition("=")
        if not sep:
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_key or not normalized_value:
            continue
        output[normalized_key] = normalized_value
    return output


def _parse_optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _build_provider_governance_warning(
    *,
    provider_name: str,
    exc: Exception,
) -> str | None:
    message = str(exc)
    if (
        "code=provider_blocked_http" not in message
        and "code=provider_rate_limited" not in message
    ):
        return None
    return governance_warning_for_provider(provider_name)


def _provider_name(provider: MarketDataProvider) -> str:
    return provider.name


def _provider_license(provider: MarketDataProvider) -> str | None:
    return provider.license_note or None


def _build_key_market_input_log_fields(
    selected_datums: dict[str, MarketDatum],
) -> dict[str, object]:
    key_fields = (
        "current_price",
        "shares_outstanding",
        "risk_free_rate",
        "beta",
        "consensus_growth_rate",
        "long_run_growth_anchor",
        "target_mean_price",
    )
    output: dict[str, object] = {}
    for field in key_fields:
        datum = selected_datums.get(field)
        if datum is None:
            continue
        payload: dict[str, object] = {
            "value": datum.value,
            "source": datum.source,
        }
        if datum.as_of is not None:
            payload["as_of"] = datum.as_of
        if datum.horizon:
            payload["horizon"] = datum.horizon
        if datum.shares_scope:
            payload["shares_scope"] = datum.shares_scope
        if datum.source_detail:
            payload["source_detail"] = datum.source_detail
        if isinstance(datum.update_cadence_days, int) and datum.update_cadence_days > 0:
            payload["update_cadence_days"] = datum.update_cadence_days
        if datum.quality_flags:
            payload["quality_flags"] = list(datum.quality_flags)
        if isinstance(datum.staleness, dict):
            payload["staleness"] = dict(datum.staleness)
        output[field] = payload
    return output


market_data_service = MarketDataService()


def recompute_market_snapshot_staleness(
    market_snapshot: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> JSONObject | None:
    if not isinstance(market_snapshot, Mapping):
        return None

    snapshot: JSONObject = dict(market_snapshot)
    raw_datums = snapshot.get("market_datums")
    if not isinstance(raw_datums, Mapping):
        return snapshot

    stale_max_days = _to_int(snapshot.get("market_stale_max_days"))
    if stale_max_days is None:
        stale_max_days = _market_stale_max_days()
    stale_max_days = max(stale_max_days, 0)

    resolved_now = _resolve_staleness_now(now=now, snapshot=snapshot)
    recomputed_datums: dict[str, JSONObject] = {}
    shares_outstanding_is_stale: bool | None = None
    shares_outstanding_staleness_days: int | None = None

    for field, payload in raw_datums.items():
        if not isinstance(field, str) or not isinstance(payload, Mapping):
            continue
        datum = _market_datum_from_mapping(payload)
        field_stale_max_days = _field_stale_max_days(
            field,
            datum=datum,
            default_stale_max_days=stale_max_days,
        )
        stale_days = _staleness_days(datum.as_of, now=resolved_now)
        is_stale = stale_days is not None and stale_days > field_stale_max_days
        staleness_payload: dict[str, int | bool | None] = {
            "days": stale_days,
            "is_stale": is_stale,
            "max_days": field_stale_max_days,
        }
        datum_payload: JSONObject = dict(payload)
        datum_payload["staleness"] = staleness_payload
        datum_payload["quality_flags"] = _updated_quality_flags(
            raw_flags=payload.get("quality_flags"),
            is_stale=is_stale,
        )
        recomputed_datums[field] = datum_payload

        if field == "shares_outstanding":
            shares_outstanding_is_stale = is_stale
            shares_outstanding_staleness_days = stale_days

    snapshot["market_datums"] = recomputed_datums
    snapshot["market_stale_max_days"] = stale_max_days
    if "shares_outstanding" in recomputed_datums:
        snapshot["shares_outstanding_is_stale"] = shares_outstanding_is_stale
        snapshot["shares_outstanding_staleness_days"] = (
            shares_outstanding_staleness_days
        )
    return snapshot


def _market_stale_max_days() -> int:
    raw = os.getenv("FUNDAMENTAL_MARKET_STALE_MAX_DAYS")
    if raw is None:
        return DEFAULT_MARKET_STALE_MAX_DAYS
    try:
        parsed = int(float(raw))
    except ValueError:
        return DEFAULT_MARKET_STALE_MAX_DAYS
    return max(parsed, 0)


def _long_run_growth_stale_max_days() -> int:
    raw = os.getenv("FUNDAMENTAL_LONG_RUN_GROWTH_STALE_MAX_DAYS")
    if raw is None:
        return DEFAULT_LONG_RUN_GROWTH_STALE_MAX_DAYS
    try:
        parsed = int(float(raw))
    except ValueError:
        return DEFAULT_LONG_RUN_GROWTH_STALE_MAX_DAYS
    return max(parsed, 0)


def _field_stale_max_days(
    field: str,
    *,
    datum: MarketDatum,
    default_stale_max_days: int,
) -> int:
    field_default = default_stale_max_days
    if field == "long_run_growth_anchor":
        # Long-run growth anchors must use a strict staleness upper bound.
        return _long_run_growth_stale_max_days()

    cadence_days = datum.update_cadence_days
    if not isinstance(cadence_days, int) or cadence_days <= 0:
        return field_default

    # Keep staleness policy aligned with each series cadence.
    cadence_guardrail = cadence_days * 2
    return max(field_default, cadence_guardrail)


def _attach_staleness(
    *,
    datums: dict[str, MarketDatum],
    stale_max_days: int,
    now: datetime,
) -> dict[str, MarketDatum]:
    enriched: dict[str, MarketDatum] = {}
    for field, datum in datums.items():
        field_stale_max_days = _field_stale_max_days(
            field,
            datum=datum,
            default_stale_max_days=stale_max_days,
        )
        stale_days = _staleness_days(datum.as_of, now=now)
        is_stale = stale_days is not None and stale_days > field_stale_max_days
        staleness_payload: dict[str, str | int | bool | None] = {
            "days": stale_days,
            "is_stale": is_stale,
            "max_days": field_stale_max_days,
        }
        quality_flags = list(datum.quality_flags)
        if is_stale and "stale" not in quality_flags:
            quality_flags.append("stale")
        enriched[field] = replace(
            datum,
            quality_flags=tuple(dict.fromkeys(flag for flag in quality_flags if flag)),
            staleness=staleness_payload,
        )
    return enriched


def _staleness_days(as_of: str | None, *, now: datetime) -> int | None:
    parsed = _parse_as_of(as_of)
    if parsed is None:
        return None
    return int((now.date() - parsed.date()).days)


def _parse_as_of(as_of: str | None) -> datetime | None:
    if not isinstance(as_of, str) or not as_of.strip():
        return None
    normalized = as_of.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{normalized[:10]}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_staleness(datum: MarketDatum) -> tuple[bool | None, int | None]:
    staleness = datum.staleness
    if not isinstance(staleness, dict):
        return None, None
    is_stale_raw = staleness.get("is_stale")
    staleness_days_raw = staleness.get("days")
    is_stale = is_stale_raw if isinstance(is_stale_raw, bool) else None
    staleness_days = staleness_days_raw if isinstance(staleness_days_raw, int) else None
    return is_stale, staleness_days


def _resolve_staleness_now(
    *,
    now: datetime | None,
    snapshot: Mapping[str, object],
) -> datetime:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    snapshot_as_of = _parse_as_of(_to_text(snapshot.get("as_of")))
    if snapshot_as_of is not None:
        return snapshot_as_of
    return datetime.now(timezone.utc)


def _updated_quality_flags(
    *,
    raw_flags: object,
    is_stale: bool,
) -> list[str]:
    flags: list[str] = []
    if isinstance(raw_flags, list | tuple):
        for item in raw_flags:
            if isinstance(item, str) and item:
                flags.append(item)
    if is_stale and "stale" not in flags:
        flags.append("stale")
    if not is_stale:
        flags = [flag for flag in flags if flag != "stale"]
    return flags


def _market_datum_from_mapping(payload: Mapping[str, object]) -> MarketDatum:
    value = _to_float(payload.get("value"))
    source = _to_text(payload.get("source")) or "unknown"
    as_of = _to_text(payload.get("as_of"))
    horizon = _to_text(payload.get("horizon"))
    shares_scope = _to_text(payload.get("shares_scope"))
    update_cadence_days = _to_int(payload.get("update_cadence_days"))
    source_detail = _to_text(payload.get("source_detail"))
    fallback_reason = _to_text(payload.get("fallback_reason"))
    license_note = _to_text(payload.get("license_note"))
    quality_flags = _updated_quality_flags(
        raw_flags=payload.get("quality_flags"),
        is_stale=False,
    )
    staleness = payload.get("staleness")
    normalized_staleness = dict(staleness) if isinstance(staleness, Mapping) else None
    return MarketDatum(
        value=value,
        source=source,
        as_of=as_of,
        horizon=horizon,
        shares_scope=shares_scope,
        update_cadence_days=update_cadence_days,
        source_detail=source_detail,
        quality_flags=tuple(quality_flags),
        staleness=normalized_staleness,
        fallback_reason=fallback_reason,
        license_note=license_note,
    )


def _enforce_market_datum_contract(
    *,
    datums: dict[str, MarketDatum],
) -> tuple[dict[str, MarketDatum], tuple[str, ...]]:
    normalized: dict[str, MarketDatum] = {}
    warnings: list[str] = []
    for field, datum in datums.items():
        normalized[field], field_warnings = _enforce_market_datum_contract_for_field(
            field=field,
            datum=datum,
        )
        warnings.extend(field_warnings)
    return normalized, tuple(dict.fromkeys(warnings))


def _enforce_market_datum_contract_for_field(
    *,
    field: str,
    datum: MarketDatum,
) -> tuple[MarketDatum, tuple[str, ...]]:
    source = datum.source.strip() if datum.source.strip() else "unavailable"
    value = datum.value
    horizon = datum.horizon
    shares_scope = datum.shares_scope
    fallback_reason = datum.fallback_reason
    flags = [flag for flag in datum.quality_flags if flag]
    warnings: list[str] = []

    if source != datum.source:
        flags.append("contract_normalized_source")
        if fallback_reason is None:
            fallback_reason = "contract_invalid_source"
        warnings.append(
            f"market datum contract normalized empty source for field={field}"
        )

    if field == "target_mean_price" and value is not None and not horizon:
        horizon = CANONICAL_TARGET_MEAN_HORIZON
        flags.append("contract_defaulted_horizon")
        warnings.append(
            "market datum contract defaulted target_mean_price horizon to 12m"
        )

    if field == "shares_outstanding" and value is not None and not shares_scope:
        shares_scope = CANONICAL_SHARES_SCOPE_UNKNOWN
        flags.append("shares_scope_unknown")
        warnings.append(
            "market datum contract defaulted shares_outstanding shares_scope to unknown"
        )

    return (
        replace(
            datum,
            source=source,
            value=value,
            horizon=horizon,
            shares_scope=shares_scope,
            fallback_reason=fallback_reason,
            quality_flags=tuple(dict.fromkeys(flags)),
        ),
        tuple(warnings),
    )


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return int(float(token))
        except ValueError:
            return None
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return float(token)
        except ValueError:
            return None
    return None


def _to_text(value: object) -> str | None:
    if isinstance(value, str):
        token = value.strip()
        if token:
            return token
    return None


def _free_target_consensus_enabled() -> bool:
    raw = os.getenv("FUNDAMENTAL_ENABLE_FREE_TARGET_CONSENSUS")
    if raw is None:
        return True
    normalized = raw.strip().lower()
    if not normalized:
        return True
    return normalized not in {"0", "false", "no", "off"}
