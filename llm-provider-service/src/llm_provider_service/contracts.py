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


class KeyImportItemInput(StrictModel):
    source_line: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=80)
    api_key: SecretStr = Field(min_length=20, max_length=500)


class KeyImportCreateInput(StrictModel):
    idempotency_key: str = Field(min_length=16, max_length=128)
    items: tuple[KeyImportItemInput, ...] = Field(min_length=1, max_length=500)


class KeyImportBatchIdInput(StrictModel):
    batch_id: str = Field(min_length=36, max_length=36)


class KeyImportItemSummary(StrictModel):
    source_line: int = Field(ge=1)
    label: str
    suffix: str | None = None
    status: Literal[
        "queued",
        "validating",
        "retry_wait",
        "imported",
        "duplicate",
        "invalid",
        "unavailable",
        "expired",
    ]
    error_code: (
        Literal[
            "invalid_key",
            "request_rejected",
            "rate_limited",
            "upstream_unavailable",
            "worker_attempts_exhausted",
            "staging_unavailable",
            "already_owned",
            "duplicate_in_batch",
            "already_importing",
            "retry_expired",
        ]
        | None
    ) = None
    attempts: int = Field(ge=0)
    retryable: bool = False


class KeyImportBatch(StrictModel):
    id: str
    status: Literal["queued", "processing", "completed", "completed_with_errors"]
    total_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)
    created_at: str
    updated_at: str
    items: tuple[KeyImportItemSummary, ...] = ()


class KeyImportListResult(StrictModel):
    imports: tuple[KeyImportBatch, ...]


class KeyImportResult(StrictModel):
    import_batch: KeyImportBatch


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
