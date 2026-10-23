from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from src.shared.internal_services import InternalRequestContext

SEARCH_CONTRACT_VERSION = "search.v1"
MAX_QUERY_LENGTH = 512
MAX_RESULTS = 50


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Operation(StrEnum):
    WEB = "web"
    NEWS = "news"


class Capability(StrEnum):
    WEB = "web"
    NEWS = "news"
    REGION = "region"
    TIME_RANGE = "time_range"
    SAFE_SEARCH = "safe_search"


class TimeRange(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


REGION_PATTERN = (
    r"^(?:worldwide|(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4}|"
    r"[A-Za-z]{5,8})(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*"
    r"(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*"
    r"(?:-x(?:-[A-Za-z0-9]{1,8})+)?)$"
)


class EmptyInput(WireModel):
    pass


class SearchRequestBase(WireModel):
    query: str = Field(min_length=1, max_length=512)
    result_limit: int = Field(default=10, ge=1, le=MAX_RESULTS)
    region: str | None = Field(default=None, pattern=REGION_PATTERN)
    time_range: TimeRange | None = None
    safe_search: bool = True
    timeout_seconds: int = Field(default=30, ge=1, le=60)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class WebSearchRequest(SearchRequestBase):
    operation: Literal[Operation.WEB] = Operation.WEB


class NewsSearchRequest(SearchRequestBase):
    operation: Literal[Operation.NEWS] = Operation.NEWS
    result_limit: int = Field(default=20, ge=1, le=MAX_RESULTS)


class SearchResult(WireModel):
    title: str = Field(min_length=1, max_length=1000)
    canonical_url: str = Field(min_length=1, max_length=4096)
    snippet: str = Field(default="", max_length=5000)
    provider: str = Field(min_length=1, max_length=128)
    source: str | None = Field(default=None, max_length=512)
    published_at: datetime | None = None
    image_url: str | None = Field(default=None, max_length=4096)
    provider_metadata: dict[str, dict[str, str | int | float | bool | None]] = Field(
        default_factory=dict
    )

    @field_validator("canonical_url", "image_url")
    @classmethod
    def require_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must use http or https")
        return value


class SearchOperationResult(WireModel):
    operation: Operation
    results: tuple[SearchResult, ...]


class SearchSuccess(WireModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str = Field(min_length=1, max_length=128)
    result: SearchOperationResult


class SearchErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    INVALID_PROVIDER_KEY = "INVALID_PROVIDER_KEY"
    RATE_LIMITED = "RATE_LIMITED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_MALFORMED = "UPSTREAM_MALFORMED"


class ErrorBody(WireModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=256)
    retryable: bool
    retry_after_ms: int | None = Field(default=None, ge=0)


class SearchFailure(WireModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str = Field(min_length=1, max_length=128)
    error: ErrorBody


class ProviderCapabilities(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    operations: frozenset[Operation]
    optional_fields: frozenset[Capability] = frozenset()
    key_required: bool = True


class ProviderCatalog(WireModel):
    providers: tuple[ProviderCapabilities, ...]


class ProviderKeyAddInput(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    label: str = Field(min_length=1, max_length=128)


class ProviderKeyReplaceInput(ProviderKeyAddInput):
    key_id: str = Field(min_length=1, max_length=128)


class ProviderKeyTestInput(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class ProviderKeyDeleteInput(WireModel):
    key_id: str = Field(min_length=1, max_length=128)


class KeyAddInput(ProviderKeyAddInput):
    pass


class KeyReplaceInput(ProviderKeyReplaceInput):
    pass


class KeyTestInput(ProviderKeyTestInput):
    pass


class KeyDeleteInput(ProviderKeyDeleteInput):
    pass


class ProviderKeySummary(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    suffix: str = Field(min_length=4, max_length=8)
    fingerprint: str = Field(min_length=1, max_length=128)
    enabled: bool
    priority: int = Field(ge=0)
    status: Literal["active", "disabled", "cooldown", "invalid"] = "active"
    failure_count: int = Field(default=0, ge=0)
    cooldown_until: datetime | None = None
    last_tested_at: datetime | None = None


class ProviderKeyResult(WireModel):
    provider: str
    tested: bool
    active: bool
    suffix: str
    fingerprint: str


class ProviderKeyList(WireModel):
    providers: tuple[ProviderKeySummary, ...]


class ProviderSetting(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    enabled: bool
    priority: int = Field(ge=0)
    key: ProviderKeySummary | None = None


class ProviderPreference(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    enabled: bool
    priority: int = Field(ge=0)


class UserSettings(WireModel):
    providers: tuple[ProviderSetting, ...]


class SettingsUpdateInput(WireModel):
    providers: tuple[ProviderPreference, ...] = Field(min_length=1)


class SettingsReadResult(WireModel):
    settings: UserSettings


class ProviderCatalogResult(WireModel):
    catalog: ProviderCatalog


class ProviderKeyTestResult(WireModel):
    provider: str
    valid: bool
    status: Literal["valid", "invalid", "unavailable"]


class ProviderKeyDeleteResult(WireModel):
    deleted: bool


class WebSearchEnvelope(WireModel):
    context: InternalRequestContext
    input: WebSearchRequest


class NewsSearchEnvelope(WireModel):
    context: InternalRequestContext
    input: NewsSearchRequest


class EmptyEnvelope(WireModel):
    context: InternalRequestContext
    input: EmptyInput


class SettingsEnvelope(WireModel):
    context: InternalRequestContext
    input: SettingsUpdateInput


class ProviderKeyTestEnvelope(WireModel):
    context: InternalRequestContext
    input: ProviderKeyTestInput


class ProviderKeyAddEnvelope(WireModel):
    context: InternalRequestContext
    input: ProviderKeyAddInput


class ProviderKeyReplaceEnvelope(WireModel):
    context: InternalRequestContext
    input: ProviderKeyReplaceInput


class ProviderKeyDeleteEnvelope(WireModel):
    context: InternalRequestContext
    input: ProviderKeyDeleteInput
