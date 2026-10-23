from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ChatRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[dict[str, object], ...] = ()


class ModelRoute(BaseModel):
    """The server-owned gateway route for every application LLM request.

    The alias identifies a managed LiteLLM deployment group. The selected
    OpenRouter model is an administrative setting and is deliberately absent
    from this data-plane contract so agent callers cannot override it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: str = Field(min_length=1)


class LLMRequestClass(StrEnum):
    """Latency class used to select a bounded provider retry budget."""

    INTERACTIVE = "interactive"
    BACKGROUND = "background"


class ProviderPrincipal(BaseModel):
    """Authenticated identity supplied by the application boundary.

    This is intentionally smaller than the auth capability's session model.
    Provider adapters only need a stable user identifier and must never receive
    cookies, bearer tokens, or provider credentials.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1)


class LLMAttribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_id: str | None = Field(default=None, min_length=1)
    key_fingerprint: str | None = Field(default=None, min_length=1)


class LLMAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: int = Field(ge=1)
    deployment_id: str | None = Field(default=None, min_length=1)
    key_fingerprint: str | None = Field(default=None, min_length=1)
    error_code: str | None = Field(default=None, min_length=1)


class ResolvedModelRoute(BaseModel):
    """Server-resolved route used by an infrastructure adapter.

    ``gateway_alias`` is never accepted from a browser or agent request. It is
    derived from the authenticated principal at the provider boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_alias: str = Field(min_length=1)
    gateway_alias: str = Field(min_length=1)
    attribution: LLMAttribution | None = None


class LLMRouteResolver(Protocol):
    def resolve(
        self,
        *,
        route: ModelRoute,
        principal: ProviderPrincipal | None,
    ) -> ResolvedModelRoute: ...


class CompletionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    route: ModelRoute
    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    request_class: LLMRequestClass = LLMRequestClass.INTERACTIVE
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    idempotency_key: str | None = Field(default=None, min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)
    tools: tuple[dict[str, object], ...] = ()
    tool_choice: str | dict[str, object] | None = None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)


class CompletionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    text: str
    model: str = Field(min_length=1)
    finish_reason: str | None = None
    usage: Usage | None = None
    attempt: int = Field(default=1, ge=1)
    tool_calls: tuple[dict[str, object], ...] = ()
    attribution: LLMAttribution | None = None
    attempts: tuple[LLMAttempt, ...] = ()


class StreamEvent(BaseModel):
    """A normalized stream event.

    ``delta`` events may be emitted incrementally. Once a delta or a tool call
    has been delivered, an adapter must surface an error instead of replaying
    the request against another model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["started", "delta", "completed", "error"]
    request_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    model: str = Field(min_length=1)
    text: str = ""
    usage: Usage | None = None
    tool_calls: tuple[dict[str, object], ...] = ()
    error_code: str | None = None
    error_reason: str | None = None
    attempt: int = Field(default=1, ge=1)
    attribution: LLMAttribution | None = None


_StructuredModel = TypeVar("_StructuredModel", bound=BaseModel)


class StructuredRequest(BaseModel, Generic[_StructuredModel]):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    completion: CompletionRequest
    response_schema: type[_StructuredModel]


class LLMErrorCode(StrEnum):
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    BAD_REQUEST = "bad_request"
    POLICY_REJECTED = "policy_rejected"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    MALFORMED_RESPONSE = "malformed_response"
    STREAM_INTERRUPTED = "stream_interrupted"
    CANCELLED = "cancelled"
    FAILOVER_EXHAUSTED = "failover_exhausted"
    PROVIDER_CONTEXT_MISSING = "provider_context_missing"


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        *,
        code: LLMErrorCode,
        provider: str,
        model: str,
        request_id: str,
        reason: str,
        retryable: bool,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
        attempt: int = 1,
        partial_output: str = "",
        partial_tool_calls: tuple[dict[str, object], ...] = (),
        attribution: LLMAttribution | None = None,
        attempts: tuple[LLMAttempt, ...] = (),
    ) -> None:
        self.code = code
        self.provider = provider
        self.model = model
        self.request_id = request_id
        self.reason = reason
        self.retryable = retryable
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.attempt = attempt
        self.partial_output = partial_output
        self.partial_tool_calls = partial_tool_calls
        self.attribution = attribution
        self.attempts = attempts
        super().__init__(reason)


_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class LLMProviderPort(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def complete_structured(
        self, request: StructuredRequest[_ResponseModel]
    ) -> _ResponseModel: ...

    async def acomplete(self, request: CompletionRequest) -> CompletionResult: ...

    async def acomplete_structured(
        self, request: StructuredRequest[_ResponseModel]
    ) -> _ResponseModel: ...

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]: ...

    def astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]: ...

    async def aclose(self) -> None: ...
