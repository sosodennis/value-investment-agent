import httpx
import pytest
from _llm_provider_test_helpers import _request

from src.llm_provider.entrypoint import LLMProviderError
from src.llm_provider.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)
from src.llm_provider.infrastructure.telemetry import LLMProviderTelemetry


def test_gateway_telemetry_records_retry_usage_without_prompt_content() -> None:
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0,
            jitter_seconds=0,
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "model": "openrouter/free",
                        "choices": [{"message": {"content": "ok"}}],
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 3,
                            "total_tokens": 5,
                        },
                    },
                    request=request,
                )
            ),
            base_url="http://gateway/v1",
        ),
        async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={}, request=request)
            ),
            base_url="http://gateway/v1",
        ),
        telemetry=telemetry,
    )
    provider.complete(_request())

    snapshot = telemetry.snapshot()
    assert snapshot.requests == 1
    assert snapshot.successes == 1
    assert snapshot.failures == 0
    assert snapshot.attempts == 1
    assert snapshot.prompt_tokens == 2
    assert snapshot.completion_tokens == 3
    assert snapshot.total_tokens == 5


def test_malformed_completion_records_one_failed_attempt() -> None:
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=1,
            jitter_seconds=0,
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"choices": []}, request=request
                )
            ),
            base_url="http://gateway/v1",
        ),
        async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"choices": []}, request=request
                )
            ),
            base_url="http://gateway/v1",
        ),
        telemetry=telemetry,
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request())

    assert len(raised.value.attempts) == 1
    snapshot = telemetry.snapshot()
    assert snapshot.failures == 1
    assert snapshot.attempts == 1
