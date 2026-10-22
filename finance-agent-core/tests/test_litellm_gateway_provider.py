import json

import httpx
import pytest
from _llm_provider_test_helpers import _Answer, _provider, _request

import src.llm_provider.infrastructure.gateway as gateway_module
from src.llm_provider.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    LLMErrorCode,
    LLMProviderError,
    LLMRequestClass,
    ProviderPrincipal,
    StructuredRequest,
    get_default_model_route,
)
from src.llm_provider.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)


def test_default_route_is_not_changed_by_legacy_model_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "openrouter/some-paid-model")
    monkeypatch.setenv("LLM_MODEL_ALIAS", "caller-controlled-alias")

    assert get_default_model_route().alias == "openrouter-default"


def test_production_adapter_requires_an_authenticated_provider_principal() -> None:
    provider = _provider(
        httpx.MockTransport(lambda request: httpx.Response(500)),
        require_principal=True,
    )

    with pytest.raises(LLMProviderError) as error:
        provider.complete(_request())

    assert error.value.code is LLMErrorCode.PROVIDER_CONTEXT_MISSING


def test_authenticated_users_resolve_to_distinct_gateway_pools() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        models.append(payload["model"])
        return httpx.Response(
            200,
            json={
                "model": "openrouter/free",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler), require_principal=True)
    for user_id in ("user-a", "user-b"):
        token = set_provider_principal(ProviderPrincipal(user_id=user_id))
        try:
            provider.complete(_request())
        finally:
            reset_provider_principal(token)

    assert len(models) == 2
    assert models[0].startswith("openrouter-user-")
    assert models[0] != models[1]


def test_complete_maps_openai_response_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gateway-key"
        assert request.headers["x-request-id"] == "req-1"
        assert (
            request.read()
            == b'{"model":"openrouter-default","messages":[{"role":"user","content":"hello"}],"temperature":0.0,"stream":false}'
        )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [
                    {
                        "message": {"content": "hello back"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = provider.complete(_request())

    assert result.text == "hello back"
    assert result.model == "openrouter/auto"
    assert result.usage is not None
    assert result.usage.total_tokens == 5


def test_complete_retries_transient_gateway_failure_once() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503, json={"error": {"message": "busy"}}, request=request
            )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))

    assert provider.complete(_request()).text == "ok"
    assert attempts == 2


def test_complete_records_sanitized_attempt_attribution() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                headers={
                    "x-litellm-model-id": "deployment-1",
                    "x-key-fingerprint": "sha256:0123456789abcdef",
                },
                json={"error": {"message": "temporary failure"}},
                request=request,
            )
        return httpx.Response(
            200,
            headers={
                "x-litellm-model-id": "deployment-2",
                "x-key-fingerprint": "sha256:fedcba9876543210",
            },
            json={
                "model": "openrouter/free",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    result = _provider(httpx.MockTransport(handler)).complete(_request())

    assert [item.attempt for item in result.attempts] == [1, 2]
    assert result.attempts[0].deployment_id == "deployment-1"
    assert result.attempts[0].error_code == "upstream_unavailable"
    assert result.attempts[1].deployment_id == "deployment-2"
    assert result.attempts[1].error_code is None
    assert result.attribution is not None
    assert result.attribution.key_fingerprint == "sha256:fedcba9876543210"


def test_exhausted_gateway_retries_return_attempted_metadata_without_secrets() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={
                "x-litellm-model-id": f"deployment-{calls}",
                "x-key-fingerprint": "sha256:0123456789abcdef",
            },
            json={"error": {"message": "key sk-or-v1-secret"}},
            request=request,
        )

    provider = LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0,
            jitter_seconds=0,
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
        ),
        async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
        ),
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request())

    assert calls == 2
    assert raised.value.attempt == 2
    assert [item.deployment_id for item in raised.value.attempts] == [
        "deployment-1",
        "deployment-2",
    ]
    assert all(
        item.key_fingerprint == "sha256:0123456789abcdef"
        for item in raised.value.attempts
    )
    assert "sk-or-v1-secret" not in str(raised.value)


def test_large_gateway_error_body_does_not_leak_into_errors_or_telemetry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-or-v1-private-test-key"
    prompt = "private valuation prompt"
    error_body = (f"{secret} {prompt} " + "x" * 1_000_000).encode()
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(500, content=error_body, request=request)
        ),
        config=LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=1,
            jitter_seconds=0,
        ),
    )
    request = _request().model_copy(
        update={
            "messages": (ChatMessage(role=ChatRole.USER, content=prompt),),
        }
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(request)

    assert secret not in str(raised.value)
    assert prompt not in str(raised.value)
    assert secret not in caplog.text
    assert prompt not in caplog.text


def test_complete_honors_bounded_retry_after_delay(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "30"},
                json={"error": {"message": "rate limited"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    monkeypatch.setattr(gateway_module.time, "sleep", delays.append)
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
    )
    provider = LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0.25,
            max_backoff_seconds=2.0,
        ),
        client=client,
        async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
        ),
    )

    assert provider.complete(_request()).text == "ok"
    assert attempts == 2
    assert delays == [2.0]


def test_gateway_retry_configuration_has_a_hard_attempt_ceiling(monkeypatch) -> None:
    monkeypatch.setenv("LLM_GATEWAY_MAX_ATTEMPTS", "99")
    monkeypatch.setenv("LLM_GATEWAY_MAX_ATTEMPTS_INTERACTIVE", "1")
    monkeypatch.setenv("LLM_GATEWAY_MAX_ATTEMPTS_BACKGROUND", "3")

    config = LiteLLMGatewayConfig.from_env()

    assert config.max_attempts == 3
    assert config.attempts_for(LLMRequestClass.INTERACTIVE) == 1
    assert config.attempts_for(LLMRequestClass.BACKGROUND) == 3
    with pytest.raises(ValueError, match="between 1 and 3"):
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=4,
        )


def test_retry_budget_varies_by_request_class() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 4:
            return httpx.Response(
                200,
                json={
                    "model": "openrouter/free",
                    "choices": [{"message": {"content": "ok"}}],
                },
                request=request,
            )
        return httpx.Response(
            503,
            json={"error": {"message": "temporarily unavailable"}},
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handler),
        config=LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=3,
            attempts_by_request_class=(
                (LLMRequestClass.INTERACTIVE, 1),
                (LLMRequestClass.BACKGROUND, 3),
            ),
            backoff_seconds=0,
            jitter_seconds=0,
        ),
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request(LLMRequestClass.INTERACTIVE))
    assert raised.value.attempt == 1
    assert calls == 1
    assert provider.complete(_request(LLMRequestClass.BACKGROUND)).text == "ok"
    assert calls == 4


def test_request_class_budget_cannot_exceed_global_ceiling() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={"error": {"message": "temporarily unavailable"}},
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handler),
        config=LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            attempts_by_request_class=(
                (LLMRequestClass.INTERACTIVE, 2),
                (LLMRequestClass.BACKGROUND, 3),
            ),
            backoff_seconds=0,
            jitter_seconds=0,
        ),
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request(LLMRequestClass.BACKGROUND))

    assert calls == 2
    assert raised.value.attempt == 2


@pytest.mark.asyncio
async def test_async_completion_obeys_request_class_retry_budget() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={"error": {"message": "temporarily unavailable"}},
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handler),
        config=LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            attempts_by_request_class=(
                (LLMRequestClass.INTERACTIVE, 1),
                (LLMRequestClass.BACKGROUND, 3),
            ),
            backoff_seconds=0,
            jitter_seconds=0,
        ),
    )

    with pytest.raises(LLMProviderError) as interactive_error:
        await provider.acomplete(_request(LLMRequestClass.INTERACTIVE))
    assert interactive_error.value.attempt == 1
    assert calls == 1

    with pytest.raises(LLMProviderError) as background_error:
        await provider.acomplete(_request(LLMRequestClass.BACKGROUND))
    assert background_error.value.attempt == 2
    assert calls == 3
    await provider.aclose()


def test_complete_does_not_retry_authentication_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            401,
            json={"error": {"message": "invalid gateway key"}},
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request())

    assert raised.value.code is LLMErrorCode.AUTHENTICATION_FAILED
    assert raised.value.retryable is False
    assert raised.value.reason == "gateway authentication failed"
    assert "invalid gateway key" not in raised.value.reason
    assert attempts == 1


@pytest.mark.parametrize(
    ("status", "expected_code", "expected_calls"),
    [
        (400, LLMErrorCode.BAD_REQUEST, 1),
        (422, LLMErrorCode.BAD_REQUEST, 1),
        (408, LLMErrorCode.UPSTREAM_TIMEOUT, 2),
        (429, LLMErrorCode.RATE_LIMITED, 2),
        (500, LLMErrorCode.UPSTREAM_UNAVAILABLE, 2),
        (502, LLMErrorCode.UPSTREAM_UNAVAILABLE, 2),
        (503, LLMErrorCode.UPSTREAM_UNAVAILABLE, 2),
        (504, LLMErrorCode.UPSTREAM_UNAVAILABLE, 2),
    ],
)
def test_status_failure_matrix_is_bounded_and_classified(
    status: int,
    expected_code: LLMErrorCode,
    expected_calls: int,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "secret"}})

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request())

    assert raised.value.code is expected_code
    assert raised.value.retryable is False
    assert calls == expected_calls


def test_connection_reset_is_retried_without_leaking_transport_details() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError(
                "connection reset sk-or-v1-secret", request=request
            )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))

    assert provider.complete(_request()).text == "ok"
    assert calls == 2


def test_sync_structured_completion_validates_and_sends_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert '"response_format"' in body
        assert '"name":"_Answer"' in body
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = provider.complete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"


@pytest.mark.asyncio
async def test_structured_completion_validates_pydantic_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.acomplete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"
    await provider.aclose()


@pytest.mark.asyncio
async def test_structured_request_sends_json_schema_to_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert '"response_format"' in body
        assert '"name":"_Answer"' in body
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.acomplete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"
    await provider.aclose()
