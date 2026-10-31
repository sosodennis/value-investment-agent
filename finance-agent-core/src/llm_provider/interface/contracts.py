from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class ProviderKeyCreateRequest(BaseModel):
    label: str = Field(default="OpenRouter key", min_length=1, max_length=80)
    api_key: SecretStr = Field(min_length=20, max_length=500)


class ProviderKeyResponse(BaseModel):
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


class ProviderKeyTestResponse(BaseModel):
    id: str
    passed: bool
    status: Literal["healthy", "invalid_key", "rate_limited", "unavailable"]


class ProviderKeyImportItemResponse(BaseModel):
    source_line: int
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
    attempts: int
    retryable: bool = False


class ProviderKeyImportBatchResponse(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "completed_with_errors"]
    total_count: int
    processed_count: int
    imported_count: int
    duplicate_count: int
    invalid_count: int
    retryable_count: int
    created_at: str
    updated_at: str
    items: list[ProviderKeyImportItemResponse] = Field(default_factory=list)


class ProviderKeyImportParseIssue(BaseModel):
    source_line: int
    code: Literal["invalid_key_format", "invalid_csv_row", "invalid_label"]


class ProviderKeyImportPreviewResponse(BaseModel):
    file_type: Literal["txt", "csv"]
    row_count: int
    unique_count: int
    duplicate_count: int
    issues: list[ProviderKeyImportParseIssue]


class ModelOptionResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    context_length: int | None = None


class LlmSettingsResponse(BaseModel):
    selected_model: str
    default_model: str
    models: list[ModelOptionResponse]


class LlmSettingsUpdateRequest(BaseModel):
    selected_model: str = Field(min_length=1, max_length=200)
