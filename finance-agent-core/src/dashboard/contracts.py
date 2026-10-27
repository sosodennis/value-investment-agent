from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DashboardStatus(str, Enum):
    """Observed readiness: operational, degraded, unavailable, or unresolved."""

    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class MarketMoverItem(BaseModel):
    """A quote row returned by the configured market-data provider."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(description="Ticker symbol supplied by Yahoo Finance.")
    name: str = Field(
        description="Provider company name, falling back to the ticker symbol."
    )
    price: float = Field(
        description="Latest regular-market price supplied by Yahoo Finance."
    )
    change_absolute: float = Field(
        description="Absolute regular-market price change supplied by Yahoo Finance."
    )
    change_percent: float = Field(
        description="Percentage regular-market price change supplied by Yahoo Finance."
    )
    currency: str | None = Field(
        default=None,
        description="Provider currency code, or null when Yahoo Finance omits it.",
    )
    market_state: str | None = Field(
        default=None,
        description="Provider market state, or null when Yahoo Finance omits it.",
    )
    quote_time: datetime | None = Field(
        default=None,
        description="Provider quote timestamp; missing timestamps make the response stale.",
    )


class MarketMoversResponse(BaseModel):
    """Authenticated market-data snapshot with explicit freshness and failure state."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        default="yahoo_finance",
        description="Market-data provider that supplied the quote rows.",
    )
    status: Literal["fresh", "stale", "unavailable"] = Field(
        description="Fresh means all quote timestamps are within 24 hours; stale means quotes are old or a cached last-good response is served after refresh failure; unavailable means no usable quote rows are available."
    )
    fetched_at: datetime | None = Field(
        default=None,
        description="Backend fetch time for the returned snapshot, or the original fetch time when serving cached data; null when no quote snapshot is available.",
    )
    items: list[MarketMoverItem] = Field(
        default_factory=list,
        description="Yahoo Finance most-active quotes, or an empty list when no usable quote rows are available.",
    )
    error_code: str | None = Field(
        default=None,
        description="Stable, non-sensitive refresh or freshness reason; null when the response is fresh.",
    )


class CapabilityItem(BaseModel):
    """One observed backend or downstream service readiness check."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Stable identifier of the runtime, database, or configured downstream service."
    )
    status: DashboardStatus = Field(
        description="Observed result of this capability's readiness probe."
    )
    source: str = Field(
        description="Probe implementation or dependency that owns this status."
    )
    checked_at: datetime = Field(
        description="UTC time when the backend performed this readiness check."
    )
    detail: str | None = Field(
        default=None,
        description="Stable, non-sensitive diagnostic code; never includes credentials or probe URLs.",
    )


class DashboardCapabilities(BaseModel):
    """Backend-observed service readiness; it is not a claim about every agent."""

    model_config = ConfigDict(extra="forbid")

    status: DashboardStatus = Field(
        description="Aggregate of the reported capability checks."
    )
    checked_at: datetime = Field(
        description="UTC time at which this readiness snapshot was collected."
    )
    capabilities: list[CapabilityItem] = Field(
        description="Observed runtime, database, and configured downstream service checks; an empty list means no checks were reported."
    )


class RecentAnalysisItem(BaseModel):
    """A single run owned by the authenticated account, including historical runs."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(
        description="Runtime thread identifier used with run_id to reopen this exact workspace snapshot."
    )
    run_id: str = Field(
        description="Exact workflow run identifier used with thread_id to reopen this historical run."
    )
    status: Literal[
        "queued",
        "running",
        "waiting",
        "completed",
        "failed",
        "cancelled",
        "unknown",
    ] = Field(
        description="Latest status recorded for this exact run by analysis runtime."
    )
    started_at: datetime | None = Field(
        default=None,
        description="Start time recorded by analysis runtime; null when the runtime has no start time.",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Last update time recorded by analysis runtime; null when unavailable.",
    )
    ticker: str | None = Field(
        default=None,
        description="Ticker explicitly persisted in this run's input data; null when it was not persisted.",
    )
    company_name: str | None = Field(
        default=None,
        description="Company name explicitly persisted in this run's input data; null when it was not persisted.",
    )
    summary: str | None = Field(
        default=None,
        description="Summary explicitly persisted in this run's input data; null when it was not persisted.",
    )


class RecentAnalysesResponse(BaseModel):
    """Stable, account-scoped page of persisted analysis runs."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["analysis_runtime"] = Field(
        default="analysis_runtime",
        description="Persisted run-history capability that owns these records.",
    )
    fetched_at: datetime = Field(
        description="UTC time when the backend read this page."
    )
    items: list[RecentAnalysisItem] = Field(
        default_factory=list,
        description="Runs owned by the authenticated account, ordered by started_at descending with null timestamps last, then thread_id and run_id descending; empty when the account has no matching runs.",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page in the same deterministic order; null when there are no more runs.",
    )
