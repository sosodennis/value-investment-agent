from collections.abc import AsyncIterator, Iterator

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from src.infrastructure.llm.langchain_adapter import LangChainGatewayModelAdapter
from src.shared.llm.contracts import (
    CompletionRequest,
    CompletionResult,
    LLMProviderPort,
    ModelRoute,
    StreamEvent,
    StructuredRequest,
)


class _Answer(BaseModel):
    answer: str


class _FakeProvider:
    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(
            request_id=request.request_id,
            text="plain",
            model="openrouter/auto",
            tool_calls=(
                {
                    "id": "call-1",
                    "function": {"name": "_Answer", "arguments": '{"answer":"ok"}'},
                },
            )
            if request.tools
            else (),
        )

    async def acomplete(self, request: CompletionRequest) -> CompletionResult:
        return self.complete(request)

    async def acomplete_structured(
        self, request: StructuredRequest[_Answer]
    ) -> _Answer:
        return request.response_schema(answer="ok")

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        self.requests.append(request)
        yield StreamEvent(
            kind="started",
            request_id=request.request_id,
            sequence=0,
            model="openrouter/auto",
        )
        yield StreamEvent(
            kind="delta",
            request_id=request.request_id,
            sequence=1,
            model="openrouter/auto",
            text="streamed",
        )
        yield StreamEvent(
            kind="completed",
            request_id=request.request_id,
            sequence=2,
            model="openrouter/auto",
        )

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        for event in self.stream(request):
            yield event

    async def aclose(self) -> None:
        return None


def _adapter(provider: _FakeProvider) -> LangChainGatewayModelAdapter:
    typed_provider: LLMProviderPort = provider
    return LangChainGatewayModelAdapter(
        provider=typed_provider,
        route=ModelRoute(alias="openrouter-default", candidates=("openrouter/auto",)),
    )


def test_adapter_preserves_langchain_invoke_and_request_boundary() -> None:
    provider = _FakeProvider()
    result = _adapter(provider).invoke([HumanMessage(content="hello")])

    assert result.content == "plain"
    assert provider.requests[0].messages[0].content == "hello"
    assert provider.requests[0].operation == "langchain.chat_model"


def test_adapter_preserves_structured_output_tool_parser() -> None:
    provider = _FakeProvider()
    result = _adapter(provider).with_structured_output(_Answer).invoke("hello")

    assert result == _Answer(answer="ok")
    assert provider.requests[0].tools[0]["function"]["name"] == "_Answer"


def test_adapter_preserves_stream_chunks() -> None:
    provider = _FakeProvider()
    chunks = list(_adapter(provider).stream("hello"))

    assert "".join(str(chunk.content) for chunk in chunks) == "streamed"


@pytest.mark.asyncio
async def test_adapter_supports_async_invoke() -> None:
    provider = _FakeProvider()
    result = await _adapter(provider).ainvoke("hello")

    assert result.content == "plain"
