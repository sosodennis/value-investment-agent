from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from src.agents.news.application.ports import (
    FetchContentResult,
    FinbertAnalyzerLike,
    INewsArtifactRepository,
    NewsItemFactoryLike,
    SourceFactoryLike,
)
from src.agents.news.application.use_cases.run_aggregator_node_use_case import (
    run_aggregator_node_use_case,
)
from src.agents.news.application.use_cases.run_analyst_node_use_case import (
    run_analyst_node_use_case,
)
from src.agents.news.application.use_cases.run_fetch_node_use_case import (
    run_fetch_node_use_case,
)
from src.agents.news.application.use_cases.run_search_node_use_case import (
    run_search_node_use_case,
)
from src.agents.news.application.use_cases.run_selector_node_use_case import (
    run_selector_node_use_case,
)
from src.agents.news.domain.aggregation.contracts import NewsAggregationResult
from src.llm_provider.entrypoint import LLMProviderPort, ModelRoute
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

NewsNodeResult = WorkflowNodeResult


@dataclass(frozen=True)
class NewsOrchestrator:
    port: INewsArtifactRepository
    summarize_preview: Callable[[JSONObject, list[JSONObject] | None], JSONObject]
    build_news_report_payload: Callable[
        [str, list[JSONObject], NewsAggregationResult], JSONObject
    ]
    build_output_artifact: Callable[
        [str, JSONObject, str | None], AgentOutputArtifactPayload | None
    ]

    async def run_search(
        self,
        state: Mapping[str, object],
        *,
        news_search_multi_timeframe_fn: Callable[
            [str, str | None], Awaitable[list[JSONObject]]
        ],
    ) -> NewsNodeResult:
        return await run_search_node_use_case(
            state=state,
            port=self.port,
            build_output_artifact=self.build_output_artifact,
            news_search_multi_timeframe_fn=news_search_multi_timeframe_fn,
        )

    async def run_selector(
        self,
        state: Mapping[str, object],
        *,
        llm_provider: LLMProviderPort,
        llm_route: ModelRoute,
        selector_system_prompt: str,
        selector_user_prompt: str,
    ) -> NewsNodeResult:
        return await run_selector_node_use_case(
            state=state,
            port=self.port,
            llm_provider=llm_provider,
            llm_route=llm_route,
            selector_system_prompt=selector_system_prompt,
            selector_user_prompt=selector_user_prompt,
        )

    async def run_fetch(
        self,
        state: Mapping[str, object],
        *,
        fetch_clean_text_async_fn: Callable[[str], Awaitable[FetchContentResult]],
        generate_news_id_fn: Callable[[str | None, str | None], str],
        get_source_reliability_fn: Callable[[str], float],
        item_factory: NewsItemFactoryLike,
        source_factory: SourceFactoryLike,
    ) -> NewsNodeResult:
        return await run_fetch_node_use_case(
            state=state,
            port=self.port,
            fetch_clean_text_async_fn=fetch_clean_text_async_fn,
            generate_news_id_fn=generate_news_id_fn,
            get_source_reliability_fn=get_source_reliability_fn,
            item_factory=item_factory,
            source_factory=source_factory,
        )

    async def run_analyst(
        self,
        state: Mapping[str, object],
        *,
        llm_provider: LLMProviderPort,
        llm_route: ModelRoute,
        get_finbert_analyzer_fn: Callable[[], FinbertAnalyzerLike],
        analyst_system_prompt: str,
        analyst_user_prompt_basic: str,
        analyst_user_prompt_with_finbert: str,
    ) -> NewsNodeResult:
        return await run_analyst_node_use_case(
            state=state,
            port=self.port,
            llm_provider=llm_provider,
            llm_route=llm_route,
            get_finbert_analyzer_fn=get_finbert_analyzer_fn,
            analyst_system_prompt=analyst_system_prompt,
            analyst_user_prompt_basic=analyst_user_prompt_basic,
            analyst_user_prompt_with_finbert=analyst_user_prompt_with_finbert,
        )

    async def run_aggregator(
        self,
        state: Mapping[str, object],
    ) -> NewsNodeResult:
        return await run_aggregator_node_use_case(
            state=state,
            port=self.port,
            summarize_preview=self.summarize_preview,
            build_news_report_payload=self.build_news_report_payload,
            build_output_artifact=self.build_output_artifact,
        )
