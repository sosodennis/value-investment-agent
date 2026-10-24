from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderCapabilities(StrictModel):
    provider: str
    operations: list[Literal["web", "news"]]
    optional_fields: list[
        Literal["web", "news", "region", "time_range", "safe_search"]
    ] = Field(default_factory=list)
    key_required: bool = True


class ProviderKeySummary(StrictModel):
    id: str
    provider: str
    label: str
    suffix: str
    fingerprint: str
    enabled: bool
    priority: int = Field(ge=0)
    cooldown_until: str | None = None
    failure_count: int = Field(default=0, ge=0)
    last_tested_at: str | None = None
    last_used_at: str | None = None
    status: Literal["active", "disabled", "cooldown", "invalid"] = "active"


class ProviderSetting(StrictModel):
    provider: str
    enabled: bool
    priority: int
    keys: list[ProviderKeySummary] = Field(default_factory=list)


class SearchSettingsSnapshot(StrictModel):
    providers: list[ProviderSetting]


class ProviderPreference(StrictModel):
    provider: str = Field(min_length=1, max_length=128)
    enabled: bool
    priority: int = Field(ge=0)


class ProviderKeyResult(StrictModel):
    id: str
    provider: str
    tested: bool
    active: bool
    suffix: str
    fingerprint: str


class SearchSettingsResponse(StrictModel):
    providers: list[ProviderCapabilities]
    settings: SearchSettingsSnapshot


class ProviderKeyResponse(StrictModel):
    id: str
    provider: str
    tested: bool
    active: bool
    suffix: str
    fingerprint: str


class ProviderPreferencesRequest(StrictModel):
    providers: list[ProviderPreference] = Field(min_length=1)


class ProviderKeyCreateRequest(StrictModel):
    provider: str = Field(min_length=1, max_length=128)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    label: str = Field(min_length=1, max_length=128)


class ProviderKeyReplaceRequest(ProviderKeyCreateRequest):
    key_id: str = Field(min_length=1, max_length=128)


class ProviderKeyEnabledRequest(StrictModel):
    enabled: bool
