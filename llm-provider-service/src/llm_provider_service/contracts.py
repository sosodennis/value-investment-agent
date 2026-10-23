from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.llm_provider_service.domain.contracts import (
    ChatMessage,
    LLMRequestClass,
    ModelRoute,
)

LLM_SERVICE_CONTRACT_VERSION = "llm.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompletionInput(StrictModel):
    schema_version: Literal[LLM_SERVICE_CONTRACT_VERSION]
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    route: ModelRoute
    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1, max_length=128)
    request_class: LLMRequestClass
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(gt=0.0)
    response_schema: dict[str, object] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)
    tools: tuple[dict[str, object], ...] = ()
    tool_choice: str | dict[str, object] | None = None


class SuccessResponse(StrictModel):
    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal["internal.v1"]
    schema_version: Literal[LLM_SERVICE_CONTRACT_VERSION]
    result: dict[str, object]


class StreamResponse(StrictModel):
    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal["internal.v1"]
    schema_version: Literal[LLM_SERVICE_CONTRACT_VERSION]
    sequence: int = Field(ge=0)
    event: dict[str, object]


class KeyCreateInput(StrictModel):
    api_key: SecretStr = Field(min_length=20, max_length=500)
    label: str = Field(default="OpenRouter key", min_length=1, max_length=80)


class KeyIdInput(StrictModel):
    key_id: str = Field(min_length=1, max_length=255)


class KeyReplaceInput(KeyIdInput):
    api_key: SecretStr = Field(min_length=20, max_length=500)
    label: str = Field(default="OpenRouter key", min_length=1, max_length=80)


class KeySummary(StrictModel):
    id: str
    label: str
    suffix: str
    fingerprint: str
    created_at: str | None = None
    status: str = "untested"
    last_tested_at: str | None = None
    failure_count: int = 0
    cooldown_until: str | None = None
    last_error: str | None = None
    last_used_at: str | None = None
    replacement_retire_at: str | None = None


class KeyTestResult(StrictModel):
    id: str
    passed: bool
    status: Literal["healthy", "invalid_key", "rate_limited", "unavailable"]


class ModelSummary(StrictModel):
    id: str
    name: str
    description: str | None = None
    context_length: int | None = None


class SettingsResult(StrictModel):
    selected_model: str
    default_model: Literal["openrouter/free"] = "openrouter/free"
    models: tuple[ModelSummary, ...]


class SettingsUpdateInput(StrictModel):
    selected_model: str = Field(min_length=1, max_length=200)


class KeyListResult(StrictModel):
    keys: tuple[KeySummary, ...]


class KeyMutationResult(StrictModel):
    key: KeySummary


class KeyDeleteResult(StrictModel):
    deleted: Literal[True] = True


class ErrorBody(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)
    retryable: bool
    retry_after_ms: int | None = Field(default=None, ge=0)


class ErrorResponse(StrictModel):
    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal["internal.v1"]
    error: ErrorBody
