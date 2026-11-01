from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from src.shared.internal_services import InternalPrincipal, build_internal_context

from model_inference_service.app import create_app
from model_inference_service.models import ModelStatus


@dataclass
class FakeRunner:
    operation: str
    model_revision: str = "test-revision"
    delay_seconds: float = 0.0
    loaded: bool = True
    fail_warmup: bool = False
    fail_inference: bool = False

    def __post_init__(self) -> None:
        self.load_count = 0
        self.warmup_count = 0
        self.infer_count = 0
        self.active_count = 0
        self.max_active_count = 0
        self._guard = threading.Lock()

    def load(self) -> ModelStatus:
        self.load_count += 1
        return ModelStatus(
            self.loaded, self.model_revision, "load failed" if not self.loaded else None
        )

    def warmup(self) -> None:
        self.warmup_count += 1
        if self.fail_warmup:
            raise RuntimeError("warmup failure")

    def infer(self, payload: object) -> dict[str, object]:
        with self._guard:
            self.infer_count += 1
            self.active_count += 1
            self.max_active_count = max(self.max_active_count, self.active_count)
        try:
            if self.fail_inference:
                raise RuntimeError("inference failure with private input")
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            values = cast(dict[str, object], payload)
            if self.operation == "news.sentiment":
                return {
                    "label": "positive",
                    "confidence": 0.9,
                    "scores": {"positive": 0.9, "negative": 0.05, "neutral": 0.05},
                }
            sentences = cast(list[object], values["sentences"])
            return {
                "predictions": [{"keep": True, "confidence": 0.8} for _ in sentences]
            }
        finally:
            with self._guard:
                self.active_count -= 1


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


def _context(
    correlation_id: str, *, deadline_seconds: float = 5.0
) -> dict[str, object]:
    return build_internal_context(
        principal=InternalPrincipal(
            subject_id="user-123",
            organization_id="organization-123",
            membership_id="membership-123",
        ),
        correlation_id=correlation_id,
        deadline_at=(
            deadline := datetime.now(UTC) + timedelta(seconds=deadline_seconds)
        ),
        audience="model-inference-service",
        signing_key="secret",
        issued_at=deadline - timedelta(seconds=5),
    ).model_dump(mode="json")


def _inference_body(
    operation: str,
    input_data: dict[str, object],
    *,
    correlation_id: str = "request-1",
    deadline_ms: int | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "context": _context(correlation_id, deadline_seconds=5.0),
        "schema_version": "inference.v1",
        "operation": operation,
        "input": input_data,
    }
    if deadline_ms is not None:
        body["deadline_ms"] = deadline_ms
    return body


@pytest.mark.asyncio
async def test_news_contract_readiness_auth_and_single_load(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = FakeRunner("news.sentiment")
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            ready = await client.get("/readyz")
            assert ready.status_code == 200

            unauthorized = await client.post(
                "/v1/inference",
                json=_inference_body(
                    "news.sentiment", {"text": "Revenue growth improved."}
                ),
            )
            assert unauthorized.status_code == 401
            assert unauthorized.json()["error"]["code"] == "UNAUTHENTICATED"
            assert unauthorized.json()["contract_version"] == "internal.v1"

            with caplog.at_level("INFO", logger="uvicorn.error"):
                valid = await client.post(
                    "/v1/inference",
                    headers={
                        "Authorization": "Bearer secret",
                        "X-Request-ID": "req-1",
                    },
                    json=_inference_body(
                        "news.sentiment",
                        {"text": "Revenue growth improved."},
                        correlation_id="req-1",
                        deadline_ms=500,
                    ),
                )
            assert valid.status_code == 200
            assert valid.json()["correlation_id"] == "req-1"
            assert valid.json()["contract_version"] == "internal.v1"
            assert valid.json()["model_revision"] == "test-revision"
            assert valid.json()["result"]["label"] == "positive"
            assert (await client.get("/readyz")).status_code == 200
            assert runner.load_count == 1
            assert runner.warmup_count == 1
            assert '"request_id":"req-1"' in caplog.text
            assert "Revenue growth improved." not in caplog.text
            metrics = await client.get("/metrics/")
            assert metrics.status_code == 200
            assert "model_inference_requests_total" in metrics.text
            assert "model_inference_execution_seconds" in metrics.text


@pytest.mark.asyncio
async def test_authentication_precedes_principal_context_validation() -> None:
    runner = FakeRunner("news.sentiment")
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    body = _inference_body("news.sentiment", {"text": "Revenue improved."})
    body["context"] = {
        "principal": "malformed",
        "correlation_id": "auth-order-1",
        "contract_version": "internal.v1",
        "deadline_at": "not-a-date",
    }

    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            unauthorized = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer wrong"},
                json=body,
            )
            assert unauthorized.status_code == 401
            assert unauthorized.json()["error"]["code"] == "UNAUTHENTICATED"
            assert runner.infer_count == 0

            invalid_context = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=body,
            )
            assert invalid_context.status_code == 400
            assert invalid_context.json()["error"]["code"] == "INVALID_ARGUMENT"
            assert invalid_context.json()["correlation_id"] == "auth-order-1"
            assert runner.infer_count == 0


@pytest.mark.asyncio
async def test_expired_internal_deadline_is_rejected_before_admission() -> None:
    runner = FakeRunner("news.sentiment")
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    body = _inference_body("news.sentiment", {"text": "Revenue improved."})
    body["context"] = _context("expired-1", deadline_seconds=-1)

    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            response = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=body,
            )
            assert response.status_code == 504
            assert response.json()["correlation_id"] == "expired-1"
            assert response.json()["contract_version"] == "internal.v1"
            assert response.json()["error"]["code"] == "DEADLINE_EXCEEDED"
            assert runner.infer_count == 0


@pytest.mark.asyncio
async def test_same_request_id_deduplicates_and_caches_success() -> None:
    runner = FakeRunner("news.sentiment", delay_seconds=0.05)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    body = _inference_body(
        "news.sentiment",
        {"text": "Revenue growth improved."},
        correlation_id="retry-1",
    )
    headers = {"Authorization": "Bearer secret", "X-Request-ID": "retry-1"}
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            first, duplicate = await asyncio.gather(
                client.post("/v1/inference", headers=headers, json=body),
                client.post("/v1/inference", headers=headers, json=body),
            )
            replay = await client.post("/v1/inference", headers=headers, json=body)

            assert (
                first.status_code == duplicate.status_code == replay.status_code == 200
            )
            assert first.json() == duplicate.json() == replay.json()
            assert runner.infer_count == 1

            changed = dict(body)
            changed["input"] = {"text": "Different text with the same ID."}
            mismatch = await client.post("/v1/inference", headers=headers, json=changed)
            assert mismatch.status_code == 400
            assert mismatch.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_app_rejects_empty_or_unknown_operation_configuration() -> None:
    with pytest.raises(ValueError, match="at least one"):
        create_app(runners={})
    with pytest.raises(ValueError, match="unsupported inference operations"):
        create_app(runners={"arbitrary.model": FakeRunner("arbitrary.model")})


@pytest.mark.asyncio
async def test_fls_validates_batch_and_preserves_order() -> None:
    runner = FakeRunner("sec.fls")
    app = create_app(runners={"sec.fls": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            response = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body("sec.fls", {"sentences": ["one", "two"]}),
            )
            assert response.status_code == 200
            assert len(response.json()["result"]["predictions"]) == 2

            invalid = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body("sec.fls", {"sentences": [" "]}),
            )
            assert invalid.status_code == 400
            assert invalid.json()["error"]["code"] == "INVALID_ARGUMENT"

            oversized_batch = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body("sec.fls", {"sentences": ["sentence"] * 121}),
            )
            assert oversized_batch.status_code == 400
            assert oversized_batch.json()["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_news_rejects_text_over_contract_limit() -> None:
    runner = FakeRunner("news.sentiment")
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            response = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body("news.sentiment", {"text": "x" * 12_001}),
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_fls_model_batches_at_most_32_sentences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from model_inference_service.models import FLSRunner

    runner = FLSRunner(model_name="unused", revision="unused")
    runner._model = object()
    runner._tokenizer = object()
    observed: list[int] = []

    def infer_batch(sentences: list[str], _torch: object) -> list[dict[str, object]]:
        observed.append(len(sentences))
        return [{"keep": True} for _ in sentences]

    monkeypatch.setattr(runner, "_infer_batch", infer_batch)
    monkeypatch.setitem(__import__("sys").modules, "torch", object())
    result = runner.infer({"sentences": [str(index) for index in range(120)]})

    assert observed == [32, 32, 32, 24]
    assert len(result["predictions"]) == 120  # type: ignore[arg-type]


def test_fls_warmup_primes_one_full_model_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from model_inference_service.models import FLSRunner

    runner = FLSRunner(model_name="unused", revision="unused")
    observed: list[int] = []

    def infer(payload: object) -> dict[str, object]:
        values = cast(dict[str, object], payload)
        sentences = cast(list[object], values["sentences"])
        observed.append(len(sentences))
        return {"predictions": [{"keep": True} for _ in sentences]}

    monkeypatch.setattr(runner, "infer", infer)
    runner.warmup()

    assert observed == [32]


@pytest.mark.asyncio
async def test_readiness_requires_successful_model_warmup() -> None:
    runner = FakeRunner("news.sentiment", fail_warmup=True)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            response = await client.get("/readyz")
            assert response.status_code == 503
            assert response.json() == {
                "status": "not_ready",
                "contract_version": "internal.v1",
            }
            details = await client.get("/readyz/details")
            assert details.json()["operations"]["news.sentiment"]["ready"] is False


@pytest.mark.asyncio
async def test_model_not_ready_is_a_stable_service_error() -> None:
    runner = FakeRunner("news.sentiment", loaded=False)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            response = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body("news.sentiment", {"text": "Revenue improved."}),
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "MODEL_NOT_READY"


@pytest.mark.asyncio
async def test_missing_service_token_prevents_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INFERENCE_ALLOW_INSECURE", raising=False)
    app = create_app(runners={"news.sentiment": FakeRunner("news.sentiment")})
    with pytest.raises(RuntimeError, match="INFERENCE_SERVICE_TOKEN"):
        async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
            pass


@pytest.mark.asyncio
async def test_inference_failure_does_not_expose_exception_or_input() -> None:
    runner = FakeRunner("news.sentiment", fail_inference=True)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            response = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body("news.sentiment", {"text": "private user text"}),
            )
            assert response.status_code == 500
            assert response.json()["error"]["code"] == "INFERENCE_FAILED"
            assert "private user text" not in response.text
            assert "inference failure with private input" not in response.text


@pytest.mark.asyncio
async def test_cancelled_request_returns_cancelled_error_and_releases_queued_work() -> (
    None
):
    from model_inference_service.errors import ServiceError
    from model_inference_service.runtime import OperationRuntime

    runner = FakeRunner("news.sentiment", delay_seconds=0.15)
    runtime = OperationRuntime(runner=runner, max_in_flight=1, queue_depth=1)
    await runtime.start()
    active = asyncio.create_task(runtime.submit({"text": "active"}, deadline_ms=1_000))
    await asyncio.sleep(0.01)
    queued = asyncio.create_task(runtime.submit({"text": "queued"}, deadline_ms=1_000))
    await asyncio.sleep(0)
    queued.cancel()

    with pytest.raises(ServiceError) as raised:
        await queued
    assert raised.value.code == "CANCELLED"
    assert runtime.queue_size == 0
    assert await active
    await runtime.stop(grace_seconds=1.0)


@pytest.mark.asyncio
async def test_running_cancellation_holds_worker_slot_until_inference_finishes() -> (
    None
):
    from model_inference_service.errors import ServiceError
    from model_inference_service.runtime import OperationRuntime

    runner = FakeRunner("news.sentiment", delay_seconds=0.15)
    runtime = OperationRuntime(runner=runner, max_in_flight=1, queue_depth=1)
    await runtime.start()
    active = asyncio.create_task(runtime.submit({"text": "active"}, deadline_ms=1_000))
    await asyncio.sleep(0.01)
    active.cancel()

    with pytest.raises(ServiceError) as raised:
        await active
    assert raised.value.code == "CANCELLED"
    assert runtime.in_flight == 1
    await asyncio.sleep(0.2)
    assert runtime.in_flight == 0
    assert runner.infer_count == 1
    await runtime.stop(grace_seconds=1.0)


@pytest.mark.asyncio
async def test_http_caller_cancellation_discards_result_and_keeps_slot_until_done() -> (
    None
):
    runner = FakeRunner("news.sentiment", delay_seconds=0.15)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            request = asyncio.create_task(
                client.post(
                    "/v1/inference",
                    headers={
                        "Authorization": "Bearer secret",
                        "X-Request-ID": "cancel-http-1",
                    },
                    json=_inference_body(
                        "news.sentiment",
                        {"text": "discard this result"},
                        correlation_id="cancel-http-1",
                    ),
                )
            )
            await asyncio.sleep(0.02)
            request.cancel()
            response = await request

            runtime = app.state.runtimes["news.sentiment"]
            assert response.status_code == 499
            assert runtime.in_flight == 1
            await asyncio.sleep(0.18)
            assert runtime.in_flight == 0
            assert runner.infer_count == 1


@pytest.mark.asyncio
async def test_shutdown_drains_active_work_and_rejects_new_requests() -> None:
    from model_inference_service.errors import ServiceError
    from model_inference_service.runtime import OperationRuntime

    runner = FakeRunner("news.sentiment", delay_seconds=0.05)
    runtime = OperationRuntime(runner=runner, max_in_flight=1, queue_depth=1)
    await runtime.start()
    active = asyncio.create_task(runtime.submit({"text": "active"}, deadline_ms=1_000))
    await asyncio.sleep(0.01)
    queued = asyncio.create_task(runtime.submit({"text": "queued"}, deadline_ms=1_000))
    await asyncio.sleep(0)
    stop = asyncio.create_task(runtime.stop(grace_seconds=1.0))

    with pytest.raises(ServiceError) as queued_error:
        await queued
    assert queued_error.value.code == "UNAVAILABLE"
    assert await active
    await stop
    assert not runtime.accepting
    with pytest.raises(ServiceError) as rejected:
        await runtime.submit({"text": "after-stop"}, deadline_ms=1_000)
    assert rejected.value.code == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_deadline_and_overload_are_stable() -> None:
    runner = FakeRunner("sec.fls", delay_seconds=0.2)
    app = create_app(runners={"sec.fls": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            deadline = await client.post(
                "/v1/inference",
                headers={"Authorization": "Bearer secret"},
                json=_inference_body(
                    "sec.fls", {"sentences": ["slow"]}, deadline_ms=10
                ),
            )
            assert deadline.status_code == 504
            assert deadline.json()["error"]["code"] == "DEADLINE_EXCEEDED"

            requests = [
                client.post(
                    "/v1/inference",
                    headers={"Authorization": "Bearer secret"},
                    json=_inference_body(
                        "sec.fls",
                        {"sentences": [str(index)]},
                        correlation_id=f"fls-overload-{index}",
                        deadline_ms=2_000,
                    ),
                )
                for index in range(11)
            ]
            results = await asyncio.gather(*requests)
            assert any(response.status_code == 429 for response in results)
            assert any(
                response.json().get("error", {}).get("code") == "OVERLOADED"
                for response in results
            )
            assert runner.max_active_count <= 2
            metrics = await client.get("/metrics/")
            assert any(
                line.startswith("model_inference_requests_total{")
                and 'operation="sec.fls"' in line
                and 'outcome="DEADLINE_EXCEEDED"' in line
                and float(line.rsplit(" ", 1)[-1]) >= 1
                for line in metrics.text.splitlines()
            )


@pytest.mark.asyncio
async def test_fls_admission_prefers_overload_before_queue_deadlines() -> None:
    runner = FakeRunner("sec.fls", delay_seconds=0.03)
    app = create_app(runners={"sec.fls": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/v1/inference",
                        headers={
                            "Authorization": "Bearer secret",
                            "X-Request-ID": f"fls-capacity-{index}",
                        },
                        json=_inference_body(
                            "sec.fls",
                            {
                                "sentences": [
                                    "Management expects revenue growth next year."
                                ]
                            },
                            correlation_id=f"fls-capacity-{index}",
                            deadline_ms=750,
                        ),
                    )
                    for index in range(12)
                )
            )

    success_count = sum(response.status_code == 200 for response in responses)
    overload_responses = [
        response for response in responses if response.status_code == 429
    ]
    assert 1 <= success_count <= 3
    assert len(overload_responses) >= 9
    assert success_count + len(overload_responses) == 12
    assert all(
        response.json()["error"]["code"] == "OVERLOADED"
        for response in overload_responses
    )
    assert 1 <= runner.max_active_count <= 2


@pytest.mark.asyncio
async def test_news_admission_prefers_overload_before_queue_deadlines() -> None:
    runner = FakeRunner("news.sentiment", delay_seconds=0.06)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/v1/inference",
                        headers={
                            "Authorization": "Bearer secret",
                            "X-Request-ID": f"news-capacity-{index}",
                        },
                        json=_inference_body(
                            "news.sentiment",
                            {"text": "Revenue growth improved during the quarter."},
                            correlation_id=f"news-capacity-{index}",
                            deadline_ms=500,
                        ),
                    )
                    for index in range(16)
                )
            )

    success_count = sum(response.status_code == 200 for response in responses)
    overload_responses = [
        response for response in responses if response.status_code == 429
    ]
    assert 4 <= success_count <= 8
    assert len(overload_responses) >= 8
    assert success_count + len(overload_responses) == 16
    assert all(
        response.json()["error"]["code"] == "OVERLOADED"
        for response in overload_responses
    )
    assert 1 <= runner.max_active_count <= 4


@pytest.mark.asyncio
async def test_model_inference_does_not_block_liveness() -> None:
    runner = FakeRunner("news.sentiment", delay_seconds=0.15)
    app = create_app(runners={"news.sentiment": runner}, token="secret")
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with _client(app) as client:
            request = asyncio.create_task(
                client.post(
                    "/v1/inference",
                    headers={"Authorization": "Bearer secret"},
                    json=_inference_body(
                        "news.sentiment",
                        {"text": "slow"},
                        correlation_id="live-http-1",
                    ),
                )
            )
            await asyncio.sleep(0.01)
            started = time.perf_counter()
            live = await client.get("/livez")
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert live.status_code == 200
            assert elapsed_ms < 100
            assert (await request).status_code == 200
