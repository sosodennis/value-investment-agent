from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

import api.server as server


class Runtime:
    def __init__(self) -> None:
        self.recovered_resumes = 0
        self.recovered_retries = 0
        self.closed = 0

    async def recover_pending_resumes(self) -> None:
        self.recovered_resumes += 1

    async def recover_pending_retries(self) -> None:
        self.recovered_retries += 1

    async def aclose(self) -> None:
        self.closed += 1


class NotificationWorker:
    def __init__(self) -> None:
        self.stopped = False

    async def serve(self, *, stop_event: asyncio.Event) -> None:
        await stop_event.wait()
        self.stopped = True


@pytest.mark.asyncio
async def test_application_lifespan_owns_runtime_startup_and_shutdown(
    monkeypatch,
) -> None:
    runtime = Runtime()
    worker = NotificationWorker()
    app = FastAPI()
    calls: list[str] = []

    async def build_runtime(**_kwargs):
        calls.append("build_runtime")
        return runtime

    async def check_migrations() -> None:
        calls.append("migrations")

    async def close_service(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(server, "assert_migrations_complete", check_migrations)
    monkeypatch.setattr(server, "build_analysis_runtime_service", build_runtime)
    monkeypatch.setattr(server, "get_notification_worker", lambda: worker)
    monkeypatch.setattr(server, "close_search_service", lambda: close_service("search"))
    monkeypatch.setattr(server, "close_llm_provider", lambda: close_service("llm"))
    monkeypatch.setattr(
        server, "close_model_inference", lambda: close_service("inference")
    )
    monkeypatch.setattr(
        server, "close_rate_limiter", lambda: close_service("rate_limiter")
    )

    async with server.lifespan(app):
        assert app.state.analysis_runtime is runtime
        assert runtime.recovered_resumes == 1
        assert runtime.recovered_retries == 1

    assert worker.stopped
    assert runtime.closed == 1
    assert calls == [
        "migrations",
        "build_runtime",
        "search",
        "llm",
        "inference",
        "rate_limiter",
    ]
