from collections.abc import AsyncIterator, Iterator

import pytest
from pydantic import BaseModel, ValidationError

from src.shared.llm.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    LLMErrorCode,
    LLMProviderError,
    LLMProviderPort,
    ModelRoute,
    StreamEvent,
    StructuredRequest,
    Usage,
)


class _Answer(BaseModel):
    answer: str


class _FakeProvider:
    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            request_id=request.request_id,
            text="ok",
            model=request.route.candidates[0],
        )

    async def acomplete(self, request: CompletionRequest) -> CompletionResult:
        return self.complete(request)

    async def acomplete_structured(
        self, request: StructuredRequest[_Answer]
    ) -> _Answer:
        return request.response_schema.model_validate({"answer": "ok"})

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        yield StreamEvent(
            kind="started",
            request_id=request.request_id,
            sequence=0,
            model=request.route.candidates[0],
        )
        yield StreamEvent(
            kind="delta",
            request_id=request.request_id,
            sequence=1,
            model=request.route.candidates[0],
            text="ok",
            tool_calls=({"id": "call-1", "name": "lookup"},),
        )
        yield StreamEvent(
            kind="completed",
            request_id=request.request_id,
            sequence=2,
            model=request.route.candidates[0],
            usage=Usage(total_tokens=1),
        )

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        for event in self.stream(request):
            yield event

    async def aclose(self) -> None:
        return None


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
        route=ModelRoute(alias="default", candidates=("openrouter/model",)),
        request_id="req-1",
        operation="test",
    )


def test_contract_accepts_fake_provider_and_preserves_request_metadata() -> None:
    provider: LLMProviderPort = _FakeProvider()
    result = provider.complete(_request())

    assert result.request_id == "req-1"
    assert result.model == "openrouter/model"


@pytest.mark.asyncio
async def test_structured_contract_validates_the_declared_schema() -> None:
    provider: LLMProviderPort = _FakeProvider()
    result = await provider.acomplete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"


def test_stream_contract_has_monotonic_sequence_and_terminal_usage() -> None:
    provider: LLMProviderPort = _FakeProvider()
    events = list(provider.stream(_request()))

    assert [event.kind for event in events] == ["started", "delta", "completed"]
    assert [event.sequence for event in events] == [0, 1, 2]
    assert events[1].tool_calls == ({"id": "call-1", "name": "lookup"},)
    assert events[-1].usage == Usage(total_tokens=1)


def test_request_rejects_empty_route_and_invalid_timeout() -> None:
    with pytest.raises(ValidationError):
        ModelRoute(alias="default", candidates=())
    with pytest.raises(ValidationError):
        CompletionRequest(
            messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
            route=ModelRoute(alias="default", candidates=("model",)),
            request_id="req-1",
            operation="test",
            timeout_seconds=0,
        )


def test_provider_error_has_stable_retry_and_stream_fields() -> None:
    error = LLMProviderError(
        code=LLMErrorCode.STREAM_INTERRUPTED,
        provider="openrouter",
        model="openrouter/model",
        request_id="req-1",
        reason="connection reset",
        retryable=False,
        attempt=2,
        partial_output="partial",
    )

    assert error.code is LLMErrorCode.STREAM_INTERRUPTED
    assert error.retryable is False
    assert error.partial_output == "partial"
