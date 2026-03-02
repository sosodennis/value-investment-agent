from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from pydantic import BaseModel

from src.agents.news.application.ports import ArtifactNotFoundError
from src.agents.news.interface.contracts import NewsArtifactModel
from src.interface.artifacts.artifact_data_models import (
    NewsArticleArtifactData,
    NewsItemsListArtifactData,
    NewsSelectionArtifactData,
    SearchResultsArtifactData,
)
from src.services.artifact_manager import artifact_manager
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ARTICLE,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_NEWS_SELECTION,
    ARTIFACT_KIND_SEARCH_RESULTS,
)
from src.shared.kernel.types import JSONObject

_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass
class NewsArtifactRepository:
    search_results_port: TypedArtifactPort[SearchResultsArtifactData]
    news_selection_port: TypedArtifactPort[NewsSelectionArtifactData]
    news_article_port: TypedArtifactPort[NewsArticleArtifactData]
    news_items_port: TypedArtifactPort[NewsItemsListArtifactData]
    news_report_port: TypedArtifactPort[NewsArtifactModel]

    async def _save_port(
        self,
        port: TypedArtifactPort[_ModelT],
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def _load_port(
        self,
        port: TypedArtifactPort[_ModelT],
        artifact_id: str | None,
        *,
        context: str,
    ) -> _ModelT | None:
        return await port.load(
            artifact_id,
            context=context,
        )

    @staticmethod
    def _dump_models(items: list[BaseModel]) -> list[JSONObject]:
        return cast(
            list[JSONObject],
            [item.model_dump(mode="json") for item in items],
        )

    async def save_search_results(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self._save_port(
            self.search_results_port,
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_search_results(
        self, artifact_id: str | None
    ) -> SearchResultsArtifactData | None:
        return await self._load_port(
            self.search_results_port,
            artifact_id,
            context=f"artifact {artifact_id} search_results",
        )

    async def save_news_selection(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self._save_port(
            self.news_selection_port,
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_news_selection(
        self, artifact_id: str | None
    ) -> NewsSelectionArtifactData | None:
        return await self._load_port(
            self.news_selection_port,
            artifact_id,
            context=f"artifact {artifact_id} news_selection",
        )

    async def save_news_article(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self._save_port(
            self.news_article_port,
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_news_article(
        self, artifact_id: str | None
    ) -> NewsArticleArtifactData | None:
        return await self._load_port(
            self.news_article_port,
            artifact_id,
            context=f"artifact {artifact_id} news_article",
        )

    async def save_news_items(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self._save_port(
            self.news_items_port,
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_news_items(
        self, artifact_id: str | None
    ) -> NewsItemsListArtifactData | None:
        return await self._load_port(
            self.news_items_port,
            artifact_id,
            context=f"artifact {artifact_id} news_items_list",
        )

    async def load_search_context(
        self, search_artifact_id: str | None
    ) -> tuple[str, list[JSONObject]]:
        if not search_artifact_id:
            raise ArtifactNotFoundError(
                artifact_kind="search_results",
                artifact_id=search_artifact_id,
            )
        search_data = await self.load_search_results(search_artifact_id)
        if search_data is None:
            raise ArtifactNotFoundError(
                artifact_kind="search_results",
                artifact_id=search_artifact_id,
            )
        return (
            search_data.formatted_results,
            self._dump_models(search_data.raw_results),
        )

    async def load_fetch_context(
        self,
        search_artifact_id: str | None,
        selection_artifact_id: str | None,
    ) -> tuple[list[JSONObject], list[int]]:
        if not search_artifact_id:
            raise ArtifactNotFoundError(
                artifact_kind="search_results",
                artifact_id=search_artifact_id,
            )
        if not selection_artifact_id:
            raise ArtifactNotFoundError(
                artifact_kind="news_selection",
                artifact_id=selection_artifact_id,
            )
        search_data = await self.load_search_results(search_artifact_id)
        selection_data = await self.load_news_selection(selection_artifact_id)
        if search_data is None:
            raise ArtifactNotFoundError(
                artifact_kind="search_results",
                artifact_id=search_artifact_id,
            )
        if selection_data is None:
            raise ArtifactNotFoundError(
                artifact_kind="news_selection",
                artifact_id=selection_artifact_id,
            )
        raw_results = self._dump_models(search_data.raw_results)
        selected_indices = selection_data.selected_indices
        return raw_results, selected_indices

    async def load_news_items_data(
        self, news_items_artifact_id: str | None
    ) -> list[JSONObject]:
        if not news_items_artifact_id:
            raise ArtifactNotFoundError(
                artifact_kind="news_items_list",
                artifact_id=news_items_artifact_id,
            )
        news_items_data = await self.load_news_items(news_items_artifact_id)
        if news_items_data is None:
            raise ArtifactNotFoundError(
                artifact_kind="news_items_list",
                artifact_id=news_items_artifact_id,
            )
        return self._dump_models(news_items_data.news_items)

    async def load_news_article_text(
        self, content_artifact_id: str | None
    ) -> str | None:
        content_data = await self.load_news_article(content_artifact_id)
        if content_data is None:
            return None
        return content_data.full_text

    async def save_news_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self._save_port(
            self.news_report_port,
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


def build_default_news_artifact_repository() -> NewsArtifactRepository:
    return NewsArtifactRepository(
        search_results_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_SEARCH_RESULTS,
            model=SearchResultsArtifactData,
        ),
        news_selection_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_NEWS_SELECTION,
            model=NewsSelectionArtifactData,
        ),
        news_article_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_NEWS_ARTICLE,
            model=NewsArticleArtifactData,
        ),
        news_items_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_NEWS_ITEMS_LIST,
            model=NewsItemsListArtifactData,
        ),
        news_report_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
            model=NewsArtifactModel,
        ),
    )


__all__ = ["NewsArtifactRepository", "build_default_news_artifact_repository"]
