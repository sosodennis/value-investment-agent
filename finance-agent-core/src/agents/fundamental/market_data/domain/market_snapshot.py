from __future__ import annotations

from dataclasses import dataclass

from src.shared.kernel.types import JSONObject


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
