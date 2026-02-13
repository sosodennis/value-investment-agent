from __future__ import annotations

from dataclasses import dataclass

from src.agents.news.interface.contracts import NewsArtifactModel
from src.common.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ARTICLE,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_NEWS_SELECTION,
    ARTIFACT_KIND_SEARCH_RESULTS,
)
from src.common.types import JSONObject
from src.interface.artifact_api_models import (
    NewsArticleArtifactData,
    NewsItemsListArtifactData,
    NewsSelectionArtifactData,
    SearchResultsArtifactData,
)
from src.interface.artifact_contract_registry import parse_news_items_for_debate
from src.services.artifact_manager import artifact_manager
from src.shared.data.typed_artifact_port import TypedArtifactPort


@dataclass
class NewsArtifactPort:
    search_results_port: TypedArtifactPort[SearchResultsArtifactData]
    news_selection_port: TypedArtifactPort[NewsSelectionArtifactData]
    news_article_port: TypedArtifactPort[NewsArticleArtifactData]
    news_items_port: TypedArtifactPort[NewsItemsListArtifactData]
    news_report_port: TypedArtifactPort[NewsArtifactModel]

    async def save_search_results(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.search_results_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_search_results(
        self, artifact_id: str
    ) -> SearchResultsArtifactData | None:
        return await self.search_results_port.load(
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
        return await self.news_selection_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_news_selection(
        self, artifact_id: str
    ) -> NewsSelectionArtifactData | None:
        return await self.news_selection_port.load(
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
        return await self.news_article_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_news_article(
        self, artifact_id: str
    ) -> NewsArticleArtifactData | None:
        return await self.news_article_port.load(
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
        return await self.news_items_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_news_items(
        self, artifact_id: str
    ) -> NewsItemsListArtifactData | None:
        return await self.news_items_port.load(
            artifact_id,
            context=f"artifact {artifact_id} news_items_list",
        )

    async def load_news_items_for_debate(
        self, artifact_id: str
    ) -> list[JSONObject] | None:
        envelope = await self.search_results_port.manager.get_artifact_envelope(
            artifact_id
        )
        if envelope is None:
            return None
        return parse_news_items_for_debate(
            envelope.kind,
            envelope.data,
            context=f"artifact {artifact_id} {envelope.kind}",
        )

    async def load_search_context(
        self, search_artifact_id: object
    ) -> tuple[str, list[dict[str, object]]]:
        if not isinstance(search_artifact_id, str):
            return "", []
        search_data = await self.load_search_results(search_artifact_id)
        if search_data is None:
            return "", []
        return search_data.formatted_results, search_data.raw_results

    async def load_fetch_context(
        self,
        search_artifact_id: object,
        selection_artifact_id: object,
    ) -> tuple[list[dict[str, object]], list[int]]:
        if not isinstance(search_artifact_id, str) or not isinstance(
            selection_artifact_id, str
        ):
            return [], []
        search_data = await self.load_search_results(search_artifact_id)
        selection_data = await self.load_news_selection(selection_artifact_id)
        raw_results = search_data.raw_results if search_data is not None else []
        selected_indices = (
            selection_data.selected_indices if selection_data is not None else []
        )
        return raw_results, selected_indices

    async def load_news_items_data(self, news_items_artifact_id: object) -> list[dict]:
        if not isinstance(news_items_artifact_id, str):
            return []
        news_items_data = await self.load_news_items(news_items_artifact_id)
        if news_items_data is None:
            return []
        return news_items_data.news_items

    async def load_news_article_text(self, content_artifact_id: object) -> str | None:
        if not isinstance(content_artifact_id, str):
            return None
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
        return await self.news_report_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


news_artifact_port = NewsArtifactPort(
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
