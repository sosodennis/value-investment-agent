from __future__ import annotations

from typing import Protocol

from src.common.types import JSONObject


class ChainLike(Protocol):
    def invoke(self, payload: object) -> object: ...


class ModelDumpLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class LLMLike(Protocol):
    def with_structured_output(self, schema: type[object]) -> object: ...


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
