from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from src.llm_provider_service.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider_service.domain.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    ModelRoute,
    ProviderPrincipal,
)
from src.llm_provider_service.domain.reliability import (
    AttemptBudget,
    FailureCategory,
    FailureScope,
    RetryBudgetExhausted,
)
from src.llm_provider_service.domain.routes import (
    DEFAULT_MODEL_ALIAS,
    OrganizationScopedRouteResolver,
)
from src.llm_provider_service.infrastructure.embedded_runtime import (
    EmbeddedLiteLLMProvider,
)
from src.llm_provider_service.infrastructure.state import (
    ProviderDeployment,
    ProviderState,
)
from src.llm_provider_service.infrastructure.upstream_errors import (
    classify_exception,
)


@pytest.mark.asyncio
async def test_llm_encryption_rotation_rejects_invalid_replacement_key() -> None:
    old_key = Fernet.generate_key().decode("ascii")
    state = ProviderState(encryption_key=old_key)
    with pytest.raises(ValueError, match="Fernet keys"):
        await state.rotate_encryption_key(old_key=old_key, new_key="not-a-valid-key")
    await state.close()


def test_provider_route_requires_verified_organization_context() -> None:
    resolver = OrganizationScopedRouteResolver()
    with pytest.raises(ValueError, match="organization provider context is required"):
        resolver.resolve(
            route=ModelRoute(alias=DEFAULT_MODEL_ALIAS),
            principal=ProviderPrincipal(
                user_id="alice",
                organization_id="unscoped",
                membership_id="unscoped",
            ),
        )


def _error(*, status: int, metadata: dict[str, object] | None = None, headers=None):
    body = {"error": {"metadata": metadata or {}}}
    response = SimpleNamespace(status_code=status, body=body, headers=headers or {})
    return SimpleNamespace(status_code=status, response=response, body=body)


def test_key_limit_is_the_only_429_scope_that_rotates() -> None:
    key = classify_exception(
        _error(status=429, metadata={"limit_source": "openrouter_key_limit"}), "a"
    )
    global_limit = classify_exception(
        _error(status=429, metadata={"error_type": "rate_limit_exceeded"}), "a"
    )
    assert key.scope is FailureScope.KEY
    assert key.rotates_key
    assert global_limit.scope is FailureScope.UNKNOWN
    assert not global_limit.rotates_key


def test_credit_sources_do_not_rotate_except_key_limit() -> None:
    key_limit = classify_exception(
        _error(status=402, metadata={"limit_source": "openrouter_key_limit"}), "a"
    )
    account = classify_exception(
        _error(status=402, metadata={"limit_source": "openrouter_credits"}), "a"
    )
    inflight = classify_exception(
        _error(status=402, metadata={"limit_source": "openrouter_in_flight_budget"}),
        "a",
    )
    assert account.category is FailureCategory.CREDIT
    assert key_limit.rotates_key
    assert key_limit.retryable
    assert not account.rotates_key
    assert not inflight.rotates_key
    assert inflight.retryable


def test_contradictory_provider_metadata_does_not_rotate() -> None:
    failure = classify_exception(
        _error(
            status=429,
            metadata={
                "limit_source": "openrouter_key_limit",
                "provider_code": "upstream-rate-limit",
            },
        ),
        "a",
    )
    assert failure.scope is FailureScope.UNKNOWN
    assert not failure.rotates_key


def test_attempt_budget_counts_dispatches_and_rejects_duplicates() -> None:
    budget = AttemptBudget.from_timeout(3, 5)
    assert budget.reserve("a").attempt == 1
    with pytest.raises(RetryBudgetExhausted):
        budget.reserve("a")
    assert budget.reserve("b").attempt == 2
    assert budget.reserve("a", allow_repeat=True).attempt == 3
    with pytest.raises(RetryBudgetExhausted):
        budget.reserve("c")


def test_retry_after_accepts_http_date() -> None:
    failure = classify_exception(
        _error(
            status=429,
            metadata={"limit_source": "openrouter_credits"},
            headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"},
        ),
        "a",
    )
    assert failure.retry_after_seconds is not None
    assert failure.retry_after_seconds > 0


def test_retry_after_preserves_zero_seconds() -> None:
    failure = classify_exception(_error(status=429, headers={"Retry-After": 0}), "a")
    assert failure.retry_after_seconds == 0


def test_unauthorized_key_failure_is_rotatable() -> None:
    failure = classify_exception(_error(status=401), "a")
    assert failure.category is FailureCategory.AUTHENTICATION
    assert failure.scope is FailureScope.KEY
    assert failure.rotates_key


def test_litellm_timeout_is_classified_as_timeout() -> None:
    class Timeout(Exception):
        pass

    failure = classify_exception(Timeout("upstream timed out"), "a")
    assert failure.category is FailureCategory.TIMEOUT
    assert failure.retryable


def test_upstream_server_failure_is_retryable_without_key_rotation() -> None:
    class UpstreamUnavailable(Exception):
        status_code = 503

    failure = classify_exception(UpstreamUnavailable("temporarily unavailable"), "a")
    assert failure.category is FailureCategory.UNAVAILABLE
    assert failure.retryable
    assert not failure.rotates_key


def _runtime_request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
        route=ModelRoute(alias=DEFAULT_MODEL_ALIAS),
        request_id="reliability-1",
        operation="test",
        timeout_seconds=2,
    )


def _deployment(
    identifier: str, *, organization_id: str = "org-a"
) -> ProviderDeployment:
    return ProviderDeployment(
        id=identifier,
        organization_id=organization_id,
        label=identifier,
        suffix="1234",
        fingerprint=f"fingerprint-{identifier}",
        model="openrouter/free",
        created_at=datetime.now(UTC).isoformat(),
        status="healthy",
        failure_count=0,
        cooldown_until=None,
        last_tested_at=None,
        last_used_at=None,
        replacement_retire_at=None,
    )


class _RuntimeState:
    def __init__(self) -> None:
        self.items = [_deployment("key-a"), _deployment("key-b")]
        self.keys = {"key-a": "sk-a", "key-b": "sk-b"}

    async def list_deployments(
        self, *, organization_id: str
    ) -> list[ProviderDeployment]:
        _ = organization_id
        return [item for item in self.items if item.organization_id == organization_id]

    async def deployment_key(self, *, organization_id: str, deployment_id: str) -> str:
        _ = organization_id
        return self.keys[deployment_id]


class _Health:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.fail_writes = fail_writes
        self.failures: list[str] = []
        self.successes: list[str] = []

    async def ping(self) -> bool:
        return True

    async def get_many_strict(
        self, key_ids: list[str], *, organization_id: str
    ) -> dict[str, object]:
        _ = organization_id
        return {}

    async def record_use(self, key_id: str, *, organization_id: str) -> int:
        _ = organization_id
        _ = organization_id
        if self.fail_writes:
            raise ConnectionError("redis write failed")
        return 0

    async def record_success(
        self, key_id: str, *, organization_id: str, expected_version: int | None
    ) -> bool:
        _ = organization_id
        if self.fail_writes:
            raise ConnectionError("redis write failed")
        self.successes.append(key_id)
        return True

    async def record_failure(
        self,
        key_id: str,
        failure: object,
        *,
        organization_id: str,
        cooldown_seconds: float,
    ) -> None:
        _ = organization_id
        if self.fail_writes:
            raise ConnectionError("redis write failed")
        _ = organization_id
        self.failures.append(key_id)

    async def close(self) -> None:
        return None


class _KeyScopedLimit(RuntimeError):
    status_code = 429
    body = {"error": {"metadata": {"limit_source": "openrouter_key_limit"}}}


class _GlobalLimit(RuntimeError):
    status_code = 429
    body = {"error": {"metadata": {"error_type": "rate_limit_exceeded"}}}


@pytest.mark.asyncio
async def test_key_scoped_failure_rotates_within_one_organization_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Router:
        def __init__(self, *, model_list, **kwargs) -> None:
            self.key_id = model_list[0]["model_info"]["id"]

        async def acompletion(self, **kwargs):
            calls.append(self.key_id)
            if self.key_id == "key-a":
                raise _KeyScopedLimit()
            return SimpleNamespace(
                model="openrouter/free",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer", tool_calls=[]),
                        finish_reason="stop",
                    )
                ],
            )

    health = _Health()
    monkeypatch.setattr("litellm.Router", Router)
    runtime = EmbeddedLiteLLMProvider(_RuntimeState(), key_health=health)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        result = await runtime.acomplete(_runtime_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()

    assert result.text == "answer"
    assert calls == ["key-a", "key-b"]
    assert health.failures == ["key-a"]
    assert health.successes == ["key-b"]


@pytest.mark.asyncio
async def test_runtime_filters_deployments_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _RuntimeState()
    state.items.append(_deployment("key-bob", organization_id="org-b"))
    runtime = EmbeddedLiteLLMProvider(state, key_health=_Health())
    monkeypatch.setattr("litellm.Router", lambda **kwargs: None)
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        eligible = await runtime._eligible_deployments("org-a")
    finally:
        reset_provider_principal(token)
        await runtime.aclose()

    assert [item.id for item in eligible] == ["key-a", "key-b"]


@pytest.mark.asyncio
async def test_global_limit_retries_same_key_without_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Router:
        def __init__(self, *, model_list, **kwargs) -> None:
            self.key_id = model_list[0]["model_info"]["id"]

        async def acompletion(self, **kwargs):
            calls.append(self.key_id)
            if len(calls) == 1:
                raise _GlobalLimit()
            return SimpleNamespace(
                model="openrouter/free",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer", tool_calls=[]),
                        finish_reason="stop",
                    )
                ],
            )

    async def no_sleep(_delay: float) -> None:
        return None

    health = _Health()
    monkeypatch.setattr("litellm.Router", Router)
    monkeypatch.setattr(
        "src.llm_provider_service.infrastructure.embedded_runtime.asyncio.sleep",
        no_sleep,
    )
    runtime = EmbeddedLiteLLMProvider(_RuntimeState(), key_health=health)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        result = await runtime.acomplete(_runtime_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()

    assert result.text == "answer"
    assert calls == ["key-a", "key-a"]
    assert health.failures == ["key-a"]
    assert health.successes == ["key-a"]


@pytest.mark.asyncio
async def test_redis_write_failure_does_not_replay_successful_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class Router:
        def __init__(self, **kwargs) -> None:
            pass

        async def acompletion(self, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                model="openrouter/free",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="answer", tool_calls=[]),
                        finish_reason="stop",
                    )
                ],
            )

    monkeypatch.setattr("litellm.Router", Router)
    runtime = EmbeddedLiteLLMProvider(
        _RuntimeState(), key_health=_Health(fail_writes=True)
    )
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        result = await runtime.acomplete(_runtime_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()

    assert result.text == "answer"
    assert calls == 1


@pytest.mark.asyncio
async def test_litellm_router_zero_retries_dispatches_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import litellm
    from litellm import Router

    calls = 0

    async def fake_completion(**kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic upstream")

    monkeypatch.setattr(litellm, "acompletion", fake_completion)
    router = Router(
        model_list=[
            {
                "model_name": "synthetic",
                "litellm_params": {
                    "model": "openrouter/free",
                    "api_key": "sk-synthetic",
                },
                "model_info": {"id": "deployment-a"},
            }
        ],
        num_retries=0,
        max_fallbacks=0,
        fallbacks=[],
        default_fallbacks=[],
        allowed_fails=1_000_000,
        cooldown_time=0,
    )
    try:
        await router.acompletion(
            model="synthetic", messages=[{"role": "user", "content": "x"}]
        )
    except BaseException:
        pass
    else:
        pytest.fail("the synthetic upstream must fail")
    assert calls == 1
