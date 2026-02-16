from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.shared.kernel.types import JSONObject


class ChainLike(Protocol):
    def invoke(self, payload: object) -> ModelDumpLike: ...


class ModelDumpLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class LLMLike(Protocol):
    def with_structured_output(self, schema: type[object]) -> ChainLike: ...


class FinbertResultLike(Protocol):
    label: str
    score: float
    has_numbers: bool

    def to_dict(self) -> JSONObject: ...


class FinbertAnalyzerLike(Protocol):
    def is_available(self) -> bool: ...

    def analyze(self, content: str) -> FinbertResultLike | None: ...


class NewsArtifactTextReaderPort(Protocol):
    async def load_news_article_text(self, content_id: object) -> str | None: ...


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
    ) -> object: ...


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
        source: object,
        categories: list[str],
    ) -> ModelDumpLike: ...
