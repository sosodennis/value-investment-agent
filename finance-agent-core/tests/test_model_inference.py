from __future__ import annotations

import ast
import asyncio
import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock

import httpx
import pytest

from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.postprocess import (
    finbert_direction,
)
from src.model_inference.application.service import ModelInferenceService
from src.model_inference.application.sync_runner import BoundedSyncRunner
from src.model_inference.domain.contracts import (
    FLSPrediction,
    FLSResult,
    FLSSentencesInput,
    InferenceOperation,
    InferenceRequest,
    InferenceResult,
    NewsSentimentInput,
    NewsSentimentResult,
)
from src.model_inference.domain.errors import InferenceErrorCode, InferenceFailure
from src.model_inference.infrastructure.http_adapter import HttpInferenceAdapter
from src.model_inference.infrastructure.settings import ModelInferenceSettings


def _news_request() -> InferenceRequest:
    return InferenceRequest(
        operation=InferenceOperation.NEWS_SENTIMENT,
        input=NewsSentimentInput(text="Revenue rose 12% year over year."),
        request_id="request-123",
        deadline_ms=450,
    )


def _news_result() -> NewsSentimentResult:
    return NewsSentimentResult(
        label="positive",
        confidence=0.91,
        scores={"positive": 0.91, "negative": 0.03, "neutral": 0.06},
        has_numbers=True,
        model_revision="revision-123",
    )


def _fls_result(count: int) -> FLSResult:
    return FLSResult(
        predictions=tuple(
            FLSPrediction(keep=True, confidence=0.95) for _ in range(count)
        ),
        model_revision="revision-fls",
    )


class _RecordingTransport:
    def __init__(self, *outcomes: InferenceResult | InferenceFailure) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[InferenceRequest] = []

    def infer(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if len(self.requests) == 1:
            time.sleep(0.01)
        if isinstance(outcome, InferenceFailure):
            raise outcome
        return outcome

    async def infer_async(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, InferenceFailure):
            raise outcome
        return outcome

    async def aclose(self) -> None:
        return None


def _failure(
    code: InferenceErrorCode,
    *,
    retryable: bool = True,
    retry_after_ms: int | None = None,
) -> InferenceFailure:
    return InferenceFailure(
        code=code,
        request_id="service-request-id",
        retryable=retryable,
        retry_after_ms=retry_after_ms,
    )


def _settings() -> ModelInferenceSettings:
    return ModelInferenceSettings(
        news_url="http://news-inference",
        fls_url="http://fls-inference",
        token="test-token",
    )


def test_http_adapter_sends_versioned_news_request_and_parses_result() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://news-inference/v1/inference"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["X-Request-ID"] == "request-123"
        assert json.loads(request.content) == {
            "schema_version": "inference.v1",
            "operation": "news.sentiment",
            "deadline_ms": 450,
            "input": {"text": "Revenue rose 12% year over year."},
        }
        return httpx.Response(
            200,
            json={
                "schema_version": "inference.v1",
                "request_id": "request-123",
                "operation": "news.sentiment",
                "model_revision": "revision-123",
                "result": {
                    "label": "positive",
                    "confidence": 0.91,
                    "scores": {
                        "positive": 0.91,
                        "negative": 0.03,
                        "neutral": 0.06,
                    },
                },
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(respond),
        headers={"Authorization": "Bearer test-token"},
    )
    result = HttpInferenceAdapter(_settings(), client=client).infer(_news_request())

    assert result == _news_result()
    client.close()


@pytest.mark.asyncio
async def test_http_adapter_sends_async_news_request() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://news-inference/v1/inference"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["X-Request-ID"] == "request-123"
        return httpx.Response(
            200,
            json={
                "schema_version": "inference.v1",
                "request_id": "request-123",
                "operation": "news.sentiment",
                "model_revision": "revision-123",
                "result": {
                    "label": "positive",
                    "confidence": 0.91,
                    "scores": {
                        "positive": 0.91,
                        "negative": 0.03,
                        "neutral": 0.06,
                    },
                },
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        headers={"Authorization": "Bearer test-token"},
    )
    result = await HttpInferenceAdapter(_settings(), async_client=client).infer_async(
        _news_request()
    )

    assert result == _news_result()
    await client.aclose()


def test_http_adapter_maps_retryable_overload_and_retry_delay() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                429,
                json={
                    "schema_version": "inference.v1",
                    "request_id": "request-123",
                    "error": {
                        "code": "OVERLOADED",
                        "message": "capacity is full",
                        "retryable": True,
                        "retry_after_ms": 250,
                    },
                },
            )
        )
    )
    adapter = HttpInferenceAdapter(_settings(), client=client)

    with pytest.raises(InferenceFailure) as failure:
        adapter.infer(_news_request())

    assert failure.value.code is InferenceErrorCode.OVERLOADED
    assert failure.value.retryable is True
    assert failure.value.retry_after_ms == 250
    assert failure.value.request_id == "request-123"
    client.close()


def test_http_adapter_maps_malformed_response_to_non_retryable_failure() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "schema_version": "inference.v1",
                    "request_id": "wrong-request",
                    "operation": "news.sentiment",
                    "model_revision": "revision-123",
                    "result": {
                        "label": "positive",
                        "confidence": 0.91,
                        "scores": {"positive": 0.91},
                    },
                },
            )
        )
    )
    adapter = HttpInferenceAdapter(_settings(), client=client)

    with pytest.raises(InferenceFailure) as failure:
        adapter.infer(_news_request())

    assert failure.value.code is InferenceErrorCode.INFERENCE_FAILED
    assert failure.value.retryable is False
    client.close()


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (InferenceErrorCode.INVALID_ARGUMENT, 400),
        (InferenceErrorCode.UNAUTHENTICATED, 401),
        (InferenceErrorCode.MODEL_NOT_READY, 503),
        (InferenceErrorCode.OVERLOADED, 429),
        (InferenceErrorCode.DEADLINE_EXCEEDED, 504),
        (InferenceErrorCode.CANCELLED, 499),
        (InferenceErrorCode.UNAVAILABLE, 503),
        (InferenceErrorCode.INFERENCE_FAILED, 500),
    ],
)
def test_http_adapter_maps_all_service_error_codes(
    code: InferenceErrorCode,
    status_code: int,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                status_code,
                json={
                    "schema_version": "inference.v1",
                    "request_id": "request-123",
                    "error": {
                        "code": code.value,
                        "message": "service failure",
                        "retryable": code
                        in {
                            InferenceErrorCode.MODEL_NOT_READY,
                            InferenceErrorCode.OVERLOADED,
                            InferenceErrorCode.DEADLINE_EXCEEDED,
                            InferenceErrorCode.UNAVAILABLE,
                        },
                        "retry_after_ms": 250
                        if code is InferenceErrorCode.OVERLOADED
                        else None,
                    },
                },
            )
        )
    )

    with pytest.raises(InferenceFailure) as failure:
        HttpInferenceAdapter(_settings(), client=client).infer(_news_request())

    assert failure.value.code is code
    assert failure.value.request_id == "request-123"
    assert failure.value.retryable is (
        code
        in {
            InferenceErrorCode.MODEL_NOT_READY,
            InferenceErrorCode.OVERLOADED,
            InferenceErrorCode.DEADLINE_EXCEEDED,
            InferenceErrorCode.UNAVAILABLE,
        }
    )
    client.close()


def test_http_adapter_maps_connection_failure_to_retryable_unavailable() -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(fail))
    adapter = HttpInferenceAdapter(_settings(), client=client)

    with pytest.raises(InferenceFailure) as failure:
        adapter.infer(_news_request())

    assert failure.value.code is InferenceErrorCode.UNAVAILABLE
    assert failure.value.retryable is True
    client.close()


@pytest.mark.asyncio
async def test_news_retry_reuses_correlation_id_and_remaining_deadline() -> None:
    transport = _RecordingTransport(
        _failure(InferenceErrorCode.UNAVAILABLE, retry_after_ms=10),
        _news_result(),
    )
    result = await ModelInferenceService(transport).news_sentiment(
        "Revenue rose 12% year over year."
    )

    assert result == _news_result()
    assert len(transport.requests) == 2
    assert transport.requests[0].request_id == transport.requests[1].request_id
    assert transport.requests[1].deadline_ms < transport.requests[0].deadline_ms


@pytest.mark.asyncio
async def test_deadline_failure_is_not_retried_even_when_marked_retryable() -> None:
    transport = _RecordingTransport(
        _failure(InferenceErrorCode.DEADLINE_EXCEEDED, retry_after_ms=5),
        _news_result(),
    )

    with pytest.raises(InferenceFailure) as failure:
        await ModelInferenceService(transport).news_sentiment("Revenue rose 12%.")

    assert failure.value.code is InferenceErrorCode.DEADLINE_EXCEEDED
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_overload_without_explicit_retry_delay_is_not_retried() -> None:
    transport = _RecordingTransport(_failure(InferenceErrorCode.OVERLOADED))

    with pytest.raises(InferenceFailure) as failure:
        await ModelInferenceService(transport).news_sentiment("Revenue rose 12%.")

    assert failure.value.code is InferenceErrorCode.OVERLOADED
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_overload_retries_once_when_contract_provides_delay() -> None:
    transport = _RecordingTransport(
        _failure(InferenceErrorCode.OVERLOADED, retry_after_ms=10),
        _news_result(),
    )

    result = await ModelInferenceService(transport).news_sentiment("Revenue rose 12%.")

    assert result == _news_result()
    assert len(transport.requests) == 2
    assert transport.requests[0].request_id == transport.requests[1].request_id


def test_sync_deadline_returns_while_transport_is_still_running() -> None:
    started = Event()
    release = Event()
    finished = Event()

    class _BlockingTransport(_RecordingTransport):
        def infer(self, request: InferenceRequest) -> InferenceResult:
            self.requests.append(request)
            started.set()
            release.wait()
            finished.set()
            return _news_result()

    transport = _BlockingTransport()
    service = ModelInferenceService(transport)
    callers = ThreadPoolExecutor(max_workers=1)
    call = callers.submit(service.news_sentiment_sync, "Revenue rose 12%.")

    try:
        assert started.wait(timeout=1)
        with pytest.raises(InferenceFailure) as failure:
            call.result(timeout=1)

        assert failure.value.code is InferenceErrorCode.DEADLINE_EXCEEDED
        assert not finished.is_set()
        assert len(transport.requests) == 1
    finally:
        release.set()
        assert finished.wait(timeout=1)
        callers.shutdown(wait=True)


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_without_another_attempt() -> None:
    class _BlockingTransport(_RecordingTransport):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def infer_async(self, request: InferenceRequest) -> InferenceResult:
            self.requests.append(request)
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    transport = _BlockingTransport()
    task = asyncio.create_task(
        ModelInferenceService(transport).news_sentiment("Revenue rose 12%.")
    )
    await transport.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(transport.requests) == 1


def test_fls_batches_share_one_deadline_and_retry_budget() -> None:
    transport = _RecordingTransport(
        _fls_result(120),
        _failure(InferenceErrorCode.UNAVAILABLE, retry_after_ms=10),
        _fls_result(1),
    )
    sentences = [
        f"Management expects growth in period {index}." for index in range(121)
    ]

    result = ModelInferenceService(transport).fls_predictions(sentences)

    assert len(result.predictions) == 121
    assert [len(request.input.sentences) for request in transport.requests] == [
        120,
        1,
        1,
    ]
    assert transport.requests[0].deadline_ms == 750
    assert transport.requests[1].deadline_ms < transport.requests[0].deadline_ms
    assert transport.requests[2].deadline_ms < transport.requests[1].deadline_ms
    assert transport.requests[1].request_id == transport.requests[2].request_id
    assert transport.requests[0].request_id != transport.requests[1].request_id
    assert all(
        isinstance(request.input, FLSSentencesInput) for request in transport.requests
    )


def test_sync_runner_rejects_saturation_without_waiting_for_capacity() -> None:
    started = Event()
    release = Event()

    def blocked_work() -> str:
        started.set()
        release.wait()
        return "complete"

    runner = BoundedSyncRunner(max_workers=1)
    callers = ThreadPoolExecutor(max_workers=1)
    deadline = time.monotonic() + 5
    first_call = callers.submit(
        runner.run,
        request_id="request-1",
        deadline=deadline,
        work=blocked_work,
    )

    try:
        assert started.wait(timeout=1)
        with pytest.raises(InferenceFailure) as failure:
            runner.run(
                request_id="request-2",
                deadline=deadline,
                work=lambda: "queued",
            )

        assert failure.value.code is InferenceErrorCode.OVERLOADED
        assert failure.value.retryable is False
        assert not first_call.done()
    finally:
        release.set()
        assert first_call.result(timeout=1) == "complete"
        callers.shutdown(wait=True)
        runner.close()


def test_news_input_limit_is_checked_before_transport() -> None:
    transport = _RecordingTransport()

    with pytest.raises(InferenceFailure) as failure:
        asyncio.run(ModelInferenceService(transport).news_sentiment("x" * 12_001))

    assert failure.value.code is InferenceErrorCode.INVALID_ARGUMENT
    assert not transport.requests


@pytest.mark.parametrize(
    ("code", "expected_reason"),
    [
        (InferenceErrorCode.UNAVAILABLE, "model_unavailable"),
        (InferenceErrorCode.INFERENCE_FAILED, "inference_failed"),
    ],
)
def test_direction_review_uses_existing_fallback_on_service_failure(
    monkeypatch: pytest.MonkeyPatch,
    code: InferenceErrorCode,
    expected_reason: str,
) -> None:
    monkeypatch.setattr(finbert_direction, "_FINBERT_DIRECTION_ENABLED", True)

    class _FailingInference:
        async def news_sentiment(self, _text: str) -> NewsSentimentResult:
            raise AssertionError("async sentiment is not used by direction review")

        def news_sentiment_sync(self, _text: str) -> NewsSentimentResult:
            raise _failure(code, retryable=False)

        def fls_predictions(self, _sentences: Sequence[str]) -> FLSResult:
            raise AssertionError("FLS is not used by direction review")

    result = finbert_direction.review_signal_direction_with_finbert(
        metric="growth_outlook",
        baseline_direction="up",
        evidence=[{"full_text": "Management expects revenue to grow next year."}],
        model_inference=_FailingInference(),
    )

    assert result.reviewed is False
    assert result.accepted is False
    assert result.reason == expected_reason


def test_model_inference_proxy_resolves_the_current_service_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.model_inference.application import wiring
    from src.model_inference.entrypoint import get_model_inference

    class _FakeService:
        def __init__(self, result: NewsSentimentResult) -> None:
            self.result = result

        def news_sentiment_sync(self, _text: str) -> NewsSentimentResult:
            return self.result

    services = iter(
        [
            _FakeService(_news_result()),
            _FakeService(
                NewsSentimentResult(
                    label="negative",
                    confidence=0.8,
                    scores={"negative": 0.8},
                    has_numbers=False,
                    model_revision="revision-next",
                )
            ),
        ]
    )
    monkeypatch.setattr(
        wiring,
        "get_default_model_inference",
        lambda: next(services),
    )
    facade = get_model_inference()

    first = facade.news_sentiment_sync("first")
    second = facade.news_sentiment_sync("second")

    assert get_model_inference() is facade
    assert first.model_revision == "revision-123"
    assert second.model_revision == "revision-next"


def test_default_model_inference_constructed_once_for_concurrent_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.model_inference.application import wiring

    caller_count = 8
    callers_ready = Barrier(caller_count)
    construction_lock = Lock()
    construction_count = 0
    settings = ModelInferenceSettings(
        news_url="http://inference:8001",
        fls_url="http://inference:8001",
        token="",
    )

    class _FakeService:
        def __init__(self, _transport: object) -> None:
            nonlocal construction_count
            with construction_lock:
                construction_count += 1
            time.sleep(0.02)

    monkeypatch.setattr(wiring, "_default_model_inference", None)
    monkeypatch.setattr(
        wiring.ModelInferenceSettings,
        "from_environment",
        classmethod(lambda _cls: settings),
    )
    monkeypatch.setattr(wiring, "HttpInferenceAdapter", lambda _settings: object())
    monkeypatch.setattr(wiring, "ModelInferenceService", _FakeService)

    def get_service() -> object:
        callers_ready.wait(timeout=2)
        return wiring.get_default_model_inference()

    with ThreadPoolExecutor(max_workers=caller_count) as callers:
        services = list(callers.map(lambda _index: get_service(), range(caller_count)))

    assert len({id(service) for service in services}) == 1
    assert construction_count == 1


def test_agent_code_imports_model_inference_through_public_entrypoint_only() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "agents"
    violations: list[str] = []

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            for imported_module in imported_modules:
                if (
                    imported_module == "src.model_inference"
                    or imported_module.startswith("src.model_inference.")
                ) and imported_module != "src.model_inference.entrypoint":
                    violations.append(
                        f"{path.relative_to(source_root)}:{node.lineno}: {imported_module}"
                    )

    assert not violations, (
        "Agent code bypasses model-inference entrypoint:\n" + "\n".join(violations)
    )


def test_model_inference_domain_and_service_logic_have_no_runtime_dependencies() -> (
    None
):
    project_root = Path(__file__).resolve().parents[1]
    sources = [
        *(project_root / "src" / "model_inference" / "domain").rglob("*.py"),
        project_root / "src" / "model_inference" / "application" / "service.py",
        project_root / "src" / "model_inference" / "application" / "ports.py",
    ]
    forbidden = {"httpx", "torch", "transformers", "model_inference_service"}
    violations: list[str] = []

    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            for imported in imported_modules:
                if imported.split(".", maxsplit=1)[0] in forbidden:
                    violations.append(
                        f"{path.relative_to(project_root)}:{node.lineno}: {imported}"
                    )

    assert not violations, "Domain/application runtime dependency found:\n" + "\n".join(
        violations
    )
