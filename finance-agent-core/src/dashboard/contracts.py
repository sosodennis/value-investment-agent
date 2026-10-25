from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DashboardStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class MarketMoverItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str
    price: float
    change_absolute: float
    change_percent: float
    currency: str | None = None
    market_state: str | None = None
    quote_time: datetime | None = None


class MarketMoversResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = "yahoo_finance"
    status: Literal["fresh", "stale", "unavailable"]
    fetched_at: datetime | None = None
    items: list[MarketMoverItem] = Field(default_factory=list)
    error_code: str | None = None


class CapabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: DashboardStatus
    source: str
    checked_at: datetime
    detail: str | None = None


class DashboardCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DashboardStatus
    checked_at: datetime
    capabilities: list[CapabilityItem]


class RecentAnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    status: Literal[
        "queued",
        "running",
        "waiting",
        "completed",
        "failed",
        "cancelled",
        "unknown",
    ]
    started_at: datetime | None = None
    updated_at: datetime | None = None
    ticker: str | None = None
    company_name: str | None = None
    summary: str | None = None


class RecentAnalysesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["analysis_runtime"] = "analysis_runtime"
    fetched_at: datetime
    items: list[RecentAnalysisItem] = Field(default_factory=list)
    next_cursor: str | None = None
