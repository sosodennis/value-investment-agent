from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Protocol

import yfinance as yf
from sqlalchemy import text

from src.dashboard.contracts import (
    CapabilityItem,
    DashboardCapabilities,
    DashboardStatus,
    MarketMoverItem,
    MarketMoversResponse,
)
from src.infrastructure.database import AsyncSessionLocal
from src.model_inference.infrastructure.settings import ModelInferenceSettings


class MarketMoversPort(Protocol):
    async def fetch(self, *, limit: int) -> list[MarketMoverItem]: ...


class ReadinessPort(Protocol):
    async def check(self, *, runtime_available: bool) -> DashboardCapabilities: ...


class YahooMarketMoversProvider:
    async def fetch(self, *, limit: int) -> list[MarketMoverItem]:
        return await asyncio.to_thread(_fetch_yahoo_market_movers, limit)


def _fetch_yahoo_market_movers(limit: int) -> list[MarketMoverItem]:
    result = yf.screen("most_actives", count=limit)
    quotes = result.get("quotes", []) if isinstance(result, dict) else []
    items: list[MarketMoverItem] = []
    for quote in quotes[:limit]:
        if not isinstance(quote, dict):
            continue
        symbol = quote.get("symbol")
        price = quote.get("regularMarketPrice")
        change = quote.get("regularMarketChange")
        change_percent = quote.get("regularMarketChangePercent")
        if not isinstance(symbol, str) or not isinstance(price, int | float):
            continue
        if not isinstance(change, int | float) or not isinstance(
            change_percent, int | float
        ):
            continue
        market_time = quote.get("regularMarketTime")
        quote_time = (
            datetime.fromtimestamp(market_time, timezone.utc)
            if isinstance(market_time, int | float) and market_time > 0
            else None
        )
        items.append(
            MarketMoverItem(
                symbol=symbol,
                name=quote.get("longName") or quote.get("shortName") or symbol,
                price=float(price),
                change_absolute=float(change),
                change_percent=float(change_percent),
                currency=quote.get("currency"),
                market_state=quote.get("marketState"),
                quote_time=quote_time,
            )
        )
    return items


class HttpReadinessProvider:
    def __init__(self) -> None:
        inference = ModelInferenceSettings.from_environment()
        self._urls = {
            "llm_provider": [os.getenv("LLM_PROVIDER_SERVICE_URL", "").strip()],
            "model_inference": [inference.news_url, inference.fls_url],
            "search": [
                os.getenv("SEARCH_SERVICE_URL", "http://search-service:8003").strip()
            ],
        }

    async def check(self, *, runtime_available: bool) -> DashboardCapabilities:
        import httpx

        checked_at = datetime.now(timezone.utc)
        capabilities = [
            _capability(
                "analysis_runtime",
                DashboardStatus.OPERATIONAL
                if runtime_available
                else DashboardStatus.UNAVAILABLE,
                "backend_runtime",
                checked_at,
                None if runtime_available else "runtime_not_initialized",
            ),
            await self._database_capability(checked_at),
        ]
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            for service_id, base_urls in self._urls.items():
                if not base_urls or any(not url for url in base_urls):
                    capabilities.append(
                        _capability(
                            service_id,
                            DashboardStatus.UNKNOWN,
                            "configured_service_readiness",
                            checked_at,
                            "service_url_not_configured",
                        )
                    )
                    continue
                probe_results = await asyncio.gather(
                    *(self._probe(client, url) for url in base_urls)
                )
                if all(probe_results):
                    status, detail = DashboardStatus.OPERATIONAL, None
                else:
                    status, detail = DashboardStatus.UNAVAILABLE, "service_not_ready"
                capabilities.append(
                    _capability(
                        service_id,
                        status,
                        "configured_service_readiness",
                        checked_at,
                        detail,
                    )
                )
        statuses = {item.status for item in capabilities}
        if statuses == {DashboardStatus.OPERATIONAL}:
            overall = DashboardStatus.OPERATIONAL
        elif DashboardStatus.OPERATIONAL in statuses:
            overall = DashboardStatus.DEGRADED
        elif (
            DashboardStatus.UNKNOWN in statuses
            and DashboardStatus.UNAVAILABLE not in statuses
        ):
            overall = DashboardStatus.UNKNOWN
        else:
            overall = DashboardStatus.UNAVAILABLE
        return DashboardCapabilities(
            status=overall, checked_at=checked_at, capabilities=capabilities
        )

    @staticmethod
    async def _probe(client, base_url: str) -> bool:
        import httpx

        try:
            response = await client.get(f"{base_url.rstrip('/')}/readyz")
            body = response.json()
            return (
                response.status_code == 200
                and isinstance(body, dict)
                and body.get("status") == "ready"
            )
        except (httpx.HTTPError, ValueError):
            return False

    @staticmethod
    async def _database_capability(checked_at: datetime) -> CapabilityItem:
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            return _capability(
                "database", DashboardStatus.OPERATIONAL, "postgresql", checked_at
            )
        except Exception:
            return CapabilityItem(
                id="database",
                status=DashboardStatus.UNAVAILABLE,
                source="postgresql",
                checked_at=checked_at,
                detail="database_probe_failed",
            )


def _capability(
    capability_id: str,
    status: DashboardStatus,
    source: str,
    checked_at: datetime,
    detail: str | None = None,
) -> CapabilityItem:
    return CapabilityItem(
        id=capability_id,
        status=status,
        source=source,
        checked_at=checked_at,
        detail=detail,
    )


class MarketMoversService:
    def __init__(self, provider: MarketMoversPort) -> None:
        self._provider = provider
        self._last_good: tuple[datetime, list[MarketMoverItem]] | None = None
        self._lock = asyncio.Lock()

    async def get(self, *, limit: int) -> MarketMoversResponse:
        async with self._lock:
            now = datetime.now(timezone.utc)
            try:
                items = await self._provider.fetch(limit=limit)
                if not items:
                    raise ValueError("empty_market_data")
                self._last_good = (now, items)
                return MarketMoversResponse(
                    status="fresh", fetched_at=now, items=items[:limit]
                )
            except Exception:
                if self._last_good is not None:
                    fetched_at, items = self._last_good
                    return MarketMoversResponse(
                        status="stale",
                        fetched_at=fetched_at,
                        items=items[:limit],
                        error_code="market_data_refresh_failed",
                    )
                return MarketMoversResponse(
                    status="unavailable", error_code="market_data_unavailable"
                )
