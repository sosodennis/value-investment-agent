import httpx
from pydantic import BaseModel

from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMRequestClass,
    ModelRoute,
)
from src.llm_provider.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)


class _Answer(BaseModel):
    answer: str


def _request(
    request_class: LLMRequestClass = LLMRequestClass.INTERACTIVE,
) -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
        route=ModelRoute(alias="openrouter-default"),
        request_id="req-1",
        operation="test",
        request_class=request_class,
    )


def _provider(
    handler: httpx.MockTransport,
    *,
    require_principal: bool = False,
    config: LiteLLMGatewayConfig | None = None,
) -> LiteLLMGatewayProvider:
    client = httpx.Client(transport=handler, base_url="http://gateway/v1")
    async_client = httpx.AsyncClient(transport=handler, base_url="http://gateway/v1")
    return LiteLLMGatewayProvider(
        config
        or LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0,
            require_principal=require_principal,
        ),
        client=client,
        async_client=async_client,
    )
