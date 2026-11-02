from __future__ import annotations

import pytest

from src.analysis_runtime.application import wiring


class FakePool:
    def __init__(self, **_kwargs) -> None:
        self.opened = False
        self.closed = 0

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed += 1


class FakeSaver:
    def __init__(self, _pool: FakePool) -> None:
        self.setup_calls = 0

    async def setup(self) -> None:
        self.setup_calls += 1


class FakeHub:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.started = 0
        self.closed = 0

    async def start(self) -> None:
        self.started += 1
        if self.fail_start:
            raise RuntimeError("notification connection failed")

    async def close(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_runtime_wiring_owns_graph_pool_and_notification_hub(monkeypatch) -> None:
    pool = FakePool()
    saver = FakeSaver(pool)
    hub = FakeHub()
    monkeypatch.setattr(wiring, "AsyncConnectionPool", lambda **_kwargs: pool)
    monkeypatch.setattr(wiring, "AsyncPostgresSaver", lambda value: saver)
    monkeypatch.setattr(wiring, "PostgresNotificationHub", lambda: hub)
    monkeypatch.setattr(wiring, "_postgres_dsn", lambda: "postgresql://test")
    monkeypatch.setattr(wiring, "_build_root_graph", lambda _saver: object())

    runtime = await wiring.build_analysis_runtime_service(
        repository=object(), owner=object()
    )

    assert pool.opened
    assert saver.setup_calls == 1
    assert hub.started == 1
    await runtime.aclose()
    await runtime.aclose()
    assert hub.closed == 1
    assert pool.closed == 1


@pytest.mark.asyncio
async def test_runtime_wiring_closes_partial_resources_when_startup_fails(
    monkeypatch,
) -> None:
    pool = FakePool()
    hub = FakeHub(fail_start=True)
    monkeypatch.setattr(wiring, "AsyncConnectionPool", lambda **_kwargs: pool)
    monkeypatch.setattr(wiring, "AsyncPostgresSaver", lambda _pool: FakeSaver(pool))
    monkeypatch.setattr(wiring, "PostgresNotificationHub", lambda: hub)
    monkeypatch.setattr(wiring, "_postgres_dsn", lambda: "postgresql://test")
    monkeypatch.setattr(wiring, "_build_root_graph", lambda _saver: object())

    with pytest.raises(RuntimeError, match="notification connection failed"):
        await wiring.build_analysis_runtime_service(repository=object(), owner=object())

    assert hub.closed == 1
    assert pool.closed == 1
