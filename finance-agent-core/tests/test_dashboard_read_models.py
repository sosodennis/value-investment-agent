from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.server import app
from src.analysis_runtime.domain.contracts import AnalysisRunPage, AnalysisRunRecord
from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import require_current_user
from src.dashboard.contracts import DashboardStatus, MarketMoverItem
from src.dashboard.infrastructure import (
    HttpReadinessProvider,
    MarketMoversService,
    YahooMarketMoversProvider,
)


@pytest.fixture(autouse=True)
def auth_override():
    app.dependency_overrides[require_current_user] = lambda: Principal(
        user_id="dashboard-test-user",
        subject="dashboard-test-user",
        email="dashboard-test@example.com",
    )
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_market_movers_return_stale_cache_after_refresh_failure():
    class Provider:
        failed = False

        async def fetch(self, *, limit: int):
            if self.failed:
                raise RuntimeError("sensitive-provider-error")
            return [
                MarketMoverItem(
                    symbol="AAPL",
                    name="Apple Inc.",
                    price=200.0,
                    change_absolute=1.5,
                    change_percent=0.75,
                    currency="USD",
                    market_state="REGULAR",
                    quote_time=datetime.now(timezone.utc),
                )
            ][:limit]

    provider = Provider()
    service = MarketMoversService(provider)
    fresh = await service.get(limit=3)
    provider.failed = True
    stale = await service.get(limit=3)
    assert fresh.status == "fresh"
    assert stale.status == "stale"
    assert stale.fetched_at == fresh.fetched_at
    assert stale.error_code == "market_data_refresh_failed"
    assert "sensitive-provider-error" not in stale.model_dump_json()


@pytest.mark.asyncio
async def test_market_movers_unavailable_without_a_last_good_response():
    class FailedProvider:
        async def fetch(self, *, limit: int):
            raise RuntimeError("provider failure")

    response = await MarketMoversService(FailedProvider()).get(limit=3)
    assert response.status == "unavailable"
    assert response.items == []
    assert response.error_code == "market_data_unavailable"


@pytest.mark.asyncio
async def test_market_movers_mark_old_quotes_stale_even_when_provider_succeeds():
    class Provider:
        async def fetch(self, *, limit: int):
            return [
                MarketMoverItem(
                    symbol="AAPL",
                    name="Apple Inc.",
                    price=200.0,
                    change_absolute=1.5,
                    change_percent=0.75,
                    currency="USD",
                    market_state="CLOSED",
                    quote_time=datetime.now(timezone.utc) - timedelta(hours=25),
                )
            ][:limit]

    response = await MarketMoversService(Provider()).get(limit=3)

    assert response.status == "stale"
    assert response.error_code == "market_data_quote_stale"
    assert response.items[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_market_movers_mark_quotes_without_timestamps_stale():
    class Provider:
        async def fetch(self, *, limit: int):
            return [
                MarketMoverItem(
                    symbol="AAPL",
                    name="Apple Inc.",
                    price=200.0,
                    change_absolute=1.5,
                    change_percent=0.75,
                    currency="USD",
                    market_state="UNKNOWN",
                )
            ][:limit]

    response = await MarketMoversService(Provider()).get(limit=3)

    assert response.status == "stale"
    assert response.error_code == "market_data_quote_stale"


@pytest.mark.asyncio
async def test_yahoo_provider_parses_most_actives_quote(monkeypatch):
    market_time = 1_800_000_000
    monkeypatch.setattr(
        "src.dashboard.infrastructure.yf.screen",
        lambda query, count: {
            "quotes": [
                {
                    "symbol": "AAPL",
                    "longName": "Apple Inc.",
                    "regularMarketPrice": 250.0,
                    "regularMarketChange": 2.5,
                    "regularMarketChangePercent": 1.0,
                    "regularMarketTime": market_time,
                    "currency": "USD",
                    "marketState": "REGULAR",
                }
            ]
        },
    )
    items = await YahooMarketMoversProvider().fetch(limit=3)
    assert len(items) == 1
    assert items[0].symbol == "AAPL"
    assert items[0].change_absolute == 2.5
    assert items[0].quote_time == datetime.fromtimestamp(market_time, timezone.utc)


def test_dashboard_endpoints_require_authentication():
    app.dependency_overrides.clear()
    client = TestClient(app)
    assert client.get("/api/v1/dashboard/market-movers").status_code == 401
    assert client.get("/api/v1/dashboard/capabilities").status_code == 401
    assert client.get("/api/v1/dashboard/recent-analyses").status_code == 401


def test_recent_analyses_api_scopes_history_and_round_trips_legacy_cursor(monkeypatch):
    calls = []

    class Runtime:
        async def list_run_history(self, **kwargs):
            calls.append(kwargs)
            return AnalysisRunPage(
                runs=(
                    AnalysisRunRecord(
                        thread_id="thread-1",
                        run_id="run-1",
                        status="completed",
                        started_at=None,
                        updated_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
                        input_data={"message": "Valuate AAPL"},
                    ),
                ),
                has_more=True,
                next_started_at=None,
                next_thread_id="thread-1",
                next_run_id="run-1",
            )

    monkeypatch.setattr(app.state, "analysis_runtime", Runtime(), raising=False)
    client = TestClient(app)
    first = client.get("/api/v1/dashboard/recent-analyses?limit=1")

    assert first.status_code == 200
    payload = first.json()
    assert payload["source"] == "analysis_runtime"
    assert payload["items"] == [
        {
            "thread_id": "thread-1",
            "run_id": "run-1",
            "status": "completed",
            "started_at": None,
            "updated_at": "2026-10-25T00:00:00Z",
            "ticker": None,
            "company_name": None,
            "summary": None,
        }
    ]
    assert payload["next_cursor"]
    assert "Valuate AAPL" not in first.text
    assert calls[0]["principal_id"] == "dashboard-test-user"
    assert calls[0]["limit"] == 1

    second = client.get(
        "/api/v1/dashboard/recent-analyses",
        params={"limit": 1, "next_cursor": payload["next_cursor"]},
    )
    assert second.status_code == 200
    assert calls[1]["before_started_at"] is None
    assert calls[1]["before_thread_id"] == "thread-1"
    assert calls[1]["before_run_id"] == "run-1"


def test_recent_analyses_api_returns_explicit_empty_state_and_rejects_bad_cursor(
    monkeypatch,
):
    class Runtime:
        async def list_run_history(self, **kwargs):
            return AnalysisRunPage(runs=(), has_more=False)

    monkeypatch.setattr(app.state, "analysis_runtime", Runtime(), raising=False)
    client = TestClient(app)
    empty = client.get("/api/v1/dashboard/recent-analyses")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["next_cursor"] is None

    invalid = client.get(
        "/api/v1/dashboard/recent-analyses?next_cursor=not-a-valid-cursor"
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "invalid_cursor"


def test_market_movers_api_returns_service_contract():
    class Service:
        async def get(self, *, limit: int):
            return {
                "source": "yahoo_finance",
                "status": "unavailable",
                "fetched_at": None,
                "items": [],
                "error_code": "market_data_unavailable",
            }

    app.state.market_movers_service = Service()
    response = TestClient(app).get("/api/v1/dashboard/market-movers")
    assert response.status_code == 200
    assert response.json() == {
        "source": "yahoo_finance",
        "status": "unavailable",
        "fetched_at": None,
        "items": [],
        "error_code": "market_data_unavailable",
    }


@pytest.mark.asyncio
async def test_readiness_reports_unconfigured_downstream_as_unknown(monkeypatch):
    async def db_available(_checked_at):
        from src.dashboard.contracts import CapabilityItem

        return CapabilityItem(
            id="database",
            status=DashboardStatus.OPERATIONAL,
            source="postgresql",
            checked_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(
        HttpReadinessProvider,
        "_database_capability",
        staticmethod(db_available),
    )
    provider = HttpReadinessProvider()
    provider._urls = {
        "llm_provider": [""],
        "model_inference": ["", ""],
        "search": [""],
    }
    response = await provider.check(runtime_available=True)
    assert response.status == DashboardStatus.DEGRADED
    assert all(
        item.status == DashboardStatus.UNKNOWN
        for item in response.capabilities
        if item.id in {"llm_provider", "model_inference", "search"}
    )


@pytest.mark.asyncio
async def test_readiness_keeps_partial_downstream_probe_failure_distinct(monkeypatch):
    import httpx

    async def db_available(_checked_at):
        from src.dashboard.contracts import CapabilityItem

        return CapabilityItem(
            id="database",
            status=DashboardStatus.OPERATIONAL,
            source="postgresql",
            checked_at=datetime.now(timezone.utc),
        )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "ready"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            if "failed" in url:
                raise httpx.ConnectError("secret-url-and-token")
            return FakeResponse()

    monkeypatch.setattr(
        HttpReadinessProvider,
        "_database_capability",
        staticmethod(db_available),
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    provider = HttpReadinessProvider()
    provider._urls = {
        "llm_provider": ["https://ready.example"],
        "model_inference": [
            "https://ready.example",
            "https://failed.example/token?hidden",
        ],
        "search": [""],
    }
    response = await provider.check(runtime_available=True)
    statuses = {item.id: item.status for item in response.capabilities}
    assert response.status == DashboardStatus.DEGRADED
    assert statuses["llm_provider"] == DashboardStatus.OPERATIONAL
    assert statuses["model_inference"] == DashboardStatus.UNAVAILABLE
    assert statuses["search"] == DashboardStatus.UNKNOWN
    assert "hidden" not in response.model_dump_json()
