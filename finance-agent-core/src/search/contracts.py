from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=512)
    result_limit: int = Field(ge=1, le=50)
    region: str
    time_range: Literal["day", "week", "month", "year"] | None = None
    safe_search: bool
    timeout_seconds: int = Field(default=30, ge=1, le=60)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class WebSearchRequest(SearchRequest):
    result_limit: int = Field(default=7, ge=1, le=50)
    region: str = "en-US"
    time_range: Literal["day", "week", "month", "year"] | None = "year"
    safe_search: bool = True


class NewsSearchRequest(SearchRequest):
    result_limit: int = Field(default=10, ge=1, le=50)
    region: str = "worldwide"
    time_range: Literal["day", "week", "month", "year"]
    safe_search: bool = False


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    canonical_url: str
    snippet: str = ""
    provider: str
    source: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    provider_metadata: dict[str, dict[str, str | int | float | bool | None]] = Field(
        default_factory=dict
    )

    @field_validator("canonical_url", "image_url")
    @classmethod
    def http_urls_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must use http or https")
        return value

    @field_validator("published_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != timedelta(0)
        ):
            raise ValueError("published_at must be UTC")
        return value


class SearchOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["web", "news"]
    results: tuple[SearchResult, ...]


class SearchSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["internal.v1"]
    correlation_id: str
    result: SearchOperationResult


class SearchFailureBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    retryable: bool
    retry_after_ms: int | None = None


class SearchFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["internal.v1"]
    correlation_id: str
    error: SearchFailureBody
