from __future__ import annotations

import httpx
from pydantic import BaseModel

from src.llm_provider.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider.domain.contracts import (
    ChatMessage,
    CompletionRequest,
    ModelRoute,
    ProviderPrincipal,
    StructuredRequest,
)
from src.llm_provider.infrastructure.remote_client import LLMProviderServiceClient


class _Answer(BaseModel):
    answer: str


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role="user", content="hello"),),
        route=ModelRoute(alias="openrouter-default"),
        request_id="remote-120",
        operation="test",
    )


def test_structured_remote_call_forwards_schema_and_does_not_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = request.read()
        assert b'"response_schema"' in body
        assert request.headers["authorization"] == "Bearer internal-secret"
        return httpx.Response(
            200,
            json={
                "result": {
                    "request_id": "remote-120",
                    "text": '{"answer":"ok"}',
                    "model": "openrouter-default",
                }
            },
            request=request,
        )

    client = LLMProviderServiceClient(
        base_url="http://provider.test", token="internal-secret"
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=None)
    token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        result = client.complete_structured(
            StructuredRequest(completion=_request(), response_schema=_Answer)
        )
    finally:
        reset_provider_principal(token)
        client._client.close()

    assert result == _Answer(answer="ok")
    assert calls == 1
