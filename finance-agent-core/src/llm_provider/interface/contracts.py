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
