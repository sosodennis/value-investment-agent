from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

SEARCH_CONTRACT_VERSION = "search.v1"
MAX_QUERY_LENGTH = 500
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


class SearchRequestBase(WireModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(default=10, ge=1, le=MAX_RESULTS)
    region: str | None = Field(default=None, min_length=2, max_length=16)
    time_range: TimeRange | None = None
    safe_search: bool | None = None

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


class SearchResult(WireModel):
    title: str = Field(min_length=1, max_length=1000)
    canonical_url: str = Field(min_length=1, max_length=4096)
    snippet: str = Field(default="", max_length=5000)
    provider: str = Field(min_length=1, max_length=128)
    source: str | None = Field(default=None, max_length=512)
    published_at: datetime | None = None
    image_url: str | None = Field(default=None, max_length=4096)
    provider_metadata: dict[str, str | int | float | bool | None] = Field(
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


class SearchSuccess(WireModel):
    contract_version: Literal["internal.v1"]
    schema_version: Literal[SEARCH_CONTRACT_VERSION]
    correlation_id: str = Field(min_length=1, max_length=128)
    operation: Operation
    results: tuple[SearchResult, ...]


class SearchErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    RATE_LIMITED = "RATE_LIMITED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    MALFORMED_UPSTREAM_RESPONSE = "MALFORMED_UPSTREAM_RESPONSE"


class ErrorBody(WireModel):
    code: SearchErrorCode
    message: str = Field(min_length=1, max_length=256)
    retryable: bool
    retry_after_ms: int | None = Field(default=None, ge=0)


class SearchFailure(WireModel):
    contract_version: Literal["internal.v1"]
    schema_version: Literal[SEARCH_CONTRACT_VERSION]
    correlation_id: str = Field(min_length=1, max_length=128)
    error: ErrorBody


class ProviderCapabilities(WireModel):
    operations: frozenset[Operation]
    optional_fields: frozenset[Capability] = frozenset()


class ProviderKeyInput(WireModel):
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    label: str = Field(min_length=1, max_length=128)


class ProviderKeySummary(WireModel):
    provider: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    suffix: str = Field(min_length=4, max_length=8)
    fingerprint: str = Field(min_length=1, max_length=128)
    enabled: bool
    priority: int = Field(ge=0)


class ProviderKeyResult(WireModel):
    provider: str
    tested: bool
    active: bool
    suffix: str
    fingerprint: str


class ProviderKeyList(WireModel):
    providers: tuple[ProviderKeySummary, ...]


class ProviderKeyDelete(WireModel):
    provider: str = Field(min_length=1, max_length=128)
