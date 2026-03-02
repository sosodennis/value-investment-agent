from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from src.shared.kernel.types import JSONObject


class ArtifactNotFoundError(RuntimeError):
    def __init__(self, *, artifact_kind: str, artifact_id: str | None) -> None:
        artifact_label = artifact_id if artifact_id else "<missing>"
        super().__init__(f"{artifact_kind} artifact not found: {artifact_label}")
        self.artifact_kind = artifact_kind
        self.artifact_id = artifact_id


@dataclass(frozen=True)
class FetchContentResult:
    content: str | None
    failure_code: str | None = None
    failure_reason: str | None = None
    http_status: int | None = None

    @property
    def is_success(self) -> bool:
        return self.content is not None and self.failure_code is None

    @classmethod
    def ok(cls, content: str) -> FetchContentResult:
        return cls(content=content)

    @classmethod
    def fail(
        cls,
        *,
        code: str,
        reason: str,
        http_status: int | None = None,
    ) -> FetchContentResult:
        return cls(
            content=None,
            failure_code=code,
            failure_reason=reason,
            http_status=http_status,
        )


class ModelDumpLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class SelectorResponseLike(Protocol):
    content: object


class SelectorChainLike(Protocol):
    def invoke(self, payload: JSONObject) -> SelectorResponseLike: ...


class StructuredChainLike(Protocol):
    def invoke(self, payload: JSONObject) -> ModelDumpLike: ...


class LLMLike(Protocol):
    def with_structured_output(
        self, schema: type[BaseModel]
    ) -> StructuredChainLike: ...


class FinbertResultLike(Protocol):
    label: str
    score: float
    has_numbers: bool

    def to_dict(self) -> JSONObject: ...


class FinbertAnalyzerLike(Protocol):
    def is_available(self) -> bool: ...

    def analyze(self, content: str) -> FinbertResultLike | None: ...


class INewsArtifactRepository(Protocol):
    async def save_search_results(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_search_context(
        self, search_artifact_id: str | None
    ) -> tuple[str, list[JSONObject]]: ...

    async def save_news_selection(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_fetch_context(
        self,
        search_artifact_id: str | None,
        selection_artifact_id: str | None,
    ) -> tuple[list[JSONObject], list[int]]: ...

    async def save_news_article(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def save_news_items(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_news_items_data(
        self, news_items_artifact_id: str | None
    ) -> list[JSONObject]: ...

    async def load_news_article_text(
        self, content_artifact_id: str | None
    ) -> str | None: ...

    async def save_news_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...


class NewsArtifactTextReaderPort(Protocol):
    async def load_news_article_text(self, content_id: str | None) -> str | None: ...


class NewsArtifactArticleWriterPort(Protocol):
    async def save_news_article(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str,
    ) -> str | None: ...


class SourceFactoryLike(Protocol):
    def __call__(
        self,
        *,
        name: str,
        domain: str,
        reliability_score: float,
        author: str | None = None,
    ) -> BaseModel: ...


class NewsItemFactoryLike(Protocol):
    def __call__(
        self,
        *,
        id: str,
        url: str,
        title: str,
        snippet: str,
        full_content: str | None,
        published_at: datetime | None,
        source: BaseModel,
        categories: list[str],
    ) -> ModelDumpLike: ...
