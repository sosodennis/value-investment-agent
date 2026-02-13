from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate

from src.agents.news.application.analysis_service import (
    analyze_news_items,
    build_analysis_chains,
)
from src.agents.news.application.fetch_service import (
    build_articles_to_fetch,
    build_cleaned_search_results,
    build_news_items_from_fetch_results,
)
from src.agents.news.application.ports import LLMLike
from src.agents.news.application.selection_service import (
    format_selector_input,
    run_selector_with_fallback,
)
from src.agents.news.application.state_readers import (
    aggregator_ticker_from_state,
    company_name_from_state,
    news_items_artifact_id_from_state,
    resolved_ticker_from_state,
    search_artifact_id_from_state,
    selection_artifact_id_from_state,
)
from src.agents.news.application.state_updates import (
    build_aggregator_node_update,
    build_analyst_chain_error_update,
    build_analyst_node_update,
    build_fetch_node_update,
    build_search_node_empty_update,
    build_search_node_error_update,
    build_search_node_no_ticker_update,
    build_search_node_success_update,
    build_selector_node_update,
)
from src.agents.news.data.ports import NewsArtifactPort, news_artifact_port
from src.agents.news.domain.services import (
    aggregate_news_items,
    build_news_summary_message,
)
from src.agents.news.interface.mappers import summarize_news_for_preview
from src.agents.news.interface.serializers import build_news_report_payload
from src.common.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
)
from src.common.tools.logger import get_logger
from src.common.types import JSONObject
from src.interface.schemas import ArtifactReference, build_artifact_payload

logger = get_logger(__name__)


@dataclass(frozen=True)
class NewsNodeResult:
    update: dict[str, object]
    goto: str
    summary_message: str | None = None


@dataclass(frozen=True)
class NewsOrchestrator:
    port: NewsArtifactPort
    summarize_preview: Callable[[JSONObject, list[JSONObject] | None], JSONObject]

    async def run_search(
        self,
        state: Mapping[str, object],
        *,
        news_search_multi_timeframe_fn: Callable[
            [str, str | None], Awaitable[list[dict[str, object]]]
        ],
    ) -> NewsNodeResult:
        ticker = resolved_ticker_from_state(state)
        if not ticker:
            logger.warning("Financial News Research: No ticker resolved, skipping.")
            return NewsNodeResult(
                update=build_search_node_no_ticker_update(), goto="END"
            )

        logger.info(f"--- [News Research] Searching news for {ticker} ---")
        try:
            company_name = company_name_from_state(state)
            results = await news_search_multi_timeframe_fn(ticker, company_name)
        except Exception as exc:
            logger.error(
                f"--- [News Research] news_search CRASHED: {exc} ---", exc_info=True
            )
            return NewsNodeResult(
                update=build_search_node_error_update(str(exc)),
                goto="END",
            )

        logger.info(f"--- [News Research] Found {len(results or [])} raw results ---")
        if not results:
            return NewsNodeResult(update=build_search_node_empty_update(), goto="END")

        cleaned_results = build_cleaned_search_results(results)
        formatted_results = format_selector_input(cleaned_results)

        search_data: JSONObject = {
            "raw_results": cleaned_results,
            "formatted_results": formatted_results,
        }
        timestamp = int(time.time())
        try:
            search_artifact_id = await self.port.save_search_results(
                data=search_data,
                produced_by="financial_news_research.search_node",
                key_prefix=f"search_{ticker}_{timestamp}",
            )
            logger.info(
                f"--- [News Research] Saved search artifact (ID: {search_artifact_id}) ---"
            )
        except Exception as exc:
            logger.error(f"Failed to save search artifact: {exc}")
            search_artifact_id = None

        preview: JSONObject = {
            "status_label": "搜尋完成",
            "sentiment_display": "⚖️ PENDING ANALYSIS",
            "article_count_display": f"找到 {len(cleaned_results)} 篇新聞",
            "top_headlines": [r.get("title") for r in cleaned_results[:3]],
        }
        artifact = build_artifact_payload(
            kind=OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
            summary=f"News Research: Found {len(cleaned_results)} articles for {ticker}",
            preview=preview,
            reference=None,
        )

        return NewsNodeResult(
            update=build_search_node_success_update(
                artifact=artifact,
                article_count=len(cleaned_results),
                search_artifact_id=search_artifact_id,
            ),
            goto="selector_node",
        )

    async def run_selector(
        self,
        state: Mapping[str, object],
        *,
        get_llm_fn: Callable[[], object],
        selector_system_prompt: str,
        selector_user_prompt: str,
    ) -> NewsNodeResult:
        search_artifact_id = search_artifact_id_from_state(state)

        formatted_results = ""
        raw_results: list[dict[str, object]] = []
        is_degraded = False
        error_msg = ""

        try:
            formatted_results, raw_results = await self.port.load_search_context(
                search_artifact_id
            )
        except Exception as exc:
            logger.error(f"Failed to retrieve search artifact: {exc}")

        ticker = resolved_ticker_from_state(state)

        logger.info(f"--- [News Research] Selecting top articles for {ticker} ---")
        llm = get_llm_fn()
        prompt = ChatPromptTemplate.from_messages(
            [("system", selector_system_prompt), ("user", selector_user_prompt)]
        )
        chain = prompt | llm
        selector_result = run_selector_with_fallback(
            chain=chain,
            ticker=ticker,
            formatted_results=formatted_results,
            raw_results=raw_results,
        )
        selected_indices = selector_result.selected_indices
        if selector_result.is_degraded:
            is_degraded = True
            error_msg = selector_result.error_message

        logger.info(
            f"--- [News Research] Completed selection. Selected indices: {selected_indices} ---"
        )

        timestamp = int(time.time())
        selection_artifact_id = None
        try:
            selection_data: JSONObject = {"selected_indices": selected_indices}
            selection_artifact_id = await self.port.save_news_selection(
                data=selection_data,
                produced_by="financial_news_research.selector_node",
                key_prefix=f"selection_{ticker}_{timestamp}",
            )
        except Exception as exc:
            logger.error(f"Failed to save selection artifact: {exc}")
            is_degraded = True
            if not error_msg:
                error_msg = f"Failed to save selection artifact: {str(exc)}"

        return NewsNodeResult(
            update=build_selector_node_update(
                selection_artifact_id=selection_artifact_id,
                is_degraded=is_degraded,
                error_message=error_msg,
            ),
            goto="fetch_node",
        )

    async def run_fetch(
        self,
        state: Mapping[str, object],
        *,
        fetch_clean_text_async_fn: Callable[[str], Awaitable[str | None]],
        generate_news_id_fn: Callable[[str, str], str],
        get_source_reliability_fn: Callable[[str], float],
        item_factory: type[object],
        source_factory: type[object],
    ) -> NewsNodeResult:
        search_id = search_artifact_id_from_state(state)
        selection_id = selection_artifact_id_from_state(state)

        raw_results: list[dict[str, object]] = []
        selected_indices: list[int] = []
        article_errors: list[str] = []

        try:
            raw_results, selected_indices = await self.port.load_fetch_context(
                search_id, selection_id
            )
        except Exception as exc:
            logger.error(f"Failed to retrieve fetch artifacts: {exc}")
            article_errors.append(
                f"Failed to retrieve search/selection artifacts: {str(exc)}"
            )

        logger.info(
            f"--- [News Research] Fetching {len(selected_indices)} articles content ---"
        )

        articles_to_fetch = build_articles_to_fetch(raw_results, selected_indices)

        async def fetch_all() -> list[str | None]:
            tasks = [
                fetch_clean_text_async_fn(str(res.get("link")))
                if isinstance(res.get("link"), str)
                else asyncio.sleep(0, result=None)
                for res in articles_to_fetch
            ]
            return await asyncio.gather(*tasks)

        try:
            full_contents = await fetch_all()
        except Exception as exc:
            logger.error(
                f"Async fetch failed: {exc}. Falling back to empty contents.",
                exc_info=True,
            )
            full_contents = [None] * len(articles_to_fetch)
            article_errors.append(f"Content fetch partially failed: {str(exc)}")

        ticker = resolved_ticker_from_state(state) or ""
        timestamp = int(time.time())

        fetch_result = await build_news_items_from_fetch_results(
            articles_to_fetch=articles_to_fetch,
            full_contents=full_contents,
            ticker=ticker,
            timestamp=timestamp,
            port=self.port,
            generate_news_id_fn=generate_news_id_fn,
            get_source_reliability_fn=get_source_reliability_fn,
            item_factory=item_factory,
            source_factory=source_factory,
        )
        news_items = fetch_result.news_items
        article_errors.extend(fetch_result.article_errors)

        news_items_id = None
        try:
            news_items_id = await self.port.save_news_items(
                data={"news_items": news_items},
                produced_by="financial_news_research.fetch_node",
                key_prefix=f"news_items_{ticker}_{timestamp}",
            )
        except Exception as exc:
            logger.error(f"Failed to save news items list artifact: {exc}")

        return NewsNodeResult(
            update=build_fetch_node_update(
                news_items_id=news_items_id, article_errors=article_errors
            ),
            goto="analyst_node",
        )

    async def run_analyst(
        self,
        state: Mapping[str, object],
        *,
        get_llm_fn: Callable[[], LLMLike],
        get_finbert_analyzer_fn: Callable[[], object],
        analyst_system_prompt: str,
        analyst_user_prompt_basic: str,
        analyst_user_prompt_with_finbert: str,
        analysis_model_type: type[object],
    ) -> NewsNodeResult:
        news_items_id = news_items_artifact_id_from_state(state)

        news_items: list[dict] = []
        article_errors: list[str] = []
        try:
            news_items = await self.port.load_news_items_data(news_items_id)
        except Exception as exc:
            logger.error(f"Failed to retrieve news items: {exc}")
            article_errors.append(f"Failed to retrieve news items: {str(exc)}")

        ticker = resolved_ticker_from_state(state)

        logger.info(
            f"--- [News Research] Analyzing {len(news_items)} articles for {ticker} ---"
        )

        finbert_analyzer = get_finbert_analyzer_fn()
        llm = get_llm_fn()

        prompt_basic = ChatPromptTemplate.from_messages(
            [("system", analyst_system_prompt), ("user", analyst_user_prompt_basic)]
        )
        prompt_finbert = ChatPromptTemplate.from_messages(
            [
                ("system", analyst_system_prompt),
                ("user", analyst_user_prompt_with_finbert),
            ]
        )

        try:
            analysis_chains = build_analysis_chains(
                llm=llm,
                prompt_basic=prompt_basic,
                prompt_finbert=prompt_finbert,
                analysis_model_type=analysis_model_type,
            )
        except Exception as exc:
            logger.error(f"Failed to create chains for {ticker}: {exc}")
            return NewsNodeResult(
                update=build_analyst_chain_error_update(str(exc)),
                goto="END",
            )

        analyst_result = await analyze_news_items(
            news_items=news_items,
            ticker=ticker,
            port=self.port,
            finbert_analyzer=finbert_analyzer,
            chains=analysis_chains,
        )
        news_items = analyst_result.news_items
        article_errors.extend(analyst_result.article_errors)

        timestamp = int(time.time())
        try:
            news_items_id = await self.port.save_news_items(
                data={"news_items": news_items},
                produced_by="financial_news_research.analyst_node",
                key_prefix=f"news_items_analyzed_{ticker}_{timestamp}",
            )
        except Exception as exc:
            logger.error(f"Failed to save analyzed news items artifact: {exc}")
            news_items_id = None

        return NewsNodeResult(
            update=build_analyst_node_update(
                news_items_id=news_items_id, article_errors=article_errors
            ),
            goto="aggregator_node",
        )

    async def run_aggregator(
        self,
        state: Mapping[str, object],
        *,
        canonicalize_news_artifact_data_fn: Callable[[object], JSONObject],
    ) -> NewsNodeResult:
        news_items_id = news_items_artifact_id_from_state(state)

        news_items: list[dict] = []
        try:
            news_items = await self.port.load_news_items_data(news_items_id)
        except Exception as exc:
            logger.error(f"Failed to retrieve news items for aggregation: {exc}")

        news_item_entities = self.port.project_news_item_entities(news_items)
        ticker = aggregator_ticker_from_state(state)
        logger.info(f"--- [News Research] Aggregating results for {ticker} ---")

        aggregation = aggregate_news_items(news_item_entities, ticker=ticker)
        report_payload = build_news_report_payload(
            ticker=ticker,
            news_items=news_items,
            aggregation=aggregation,
        )
        report_data = canonicalize_news_artifact_data_fn(report_payload)

        timestamp = int(time.time())
        try:
            report_id = await self.port.save_news_report(
                data=report_data,
                produced_by="financial_news_research.aggregator_node",
                key_prefix=f"news_report_{ticker}_{timestamp}",
            )
        except Exception as exc:
            logger.error(f"Failed to save final report artifact: {exc}")
            report_id = None

        try:
            preview = self.summarize_preview(report_payload, news_items)
            reference = None
            if report_id:
                reference = ArtifactReference(
                    artifact_id=report_id,
                    download_url=f"/api/artifacts/{report_id}",
                    type=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
                )

            artifact = build_artifact_payload(
                kind=OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
                summary=f"News Research: {aggregation.sentiment_label.upper()} ({aggregation.weighted_score:.2f})",
                preview=preview,
                reference=reference,
            )
        except Exception as exc:
            logger.error(f"Failed to generate news artifact: {exc}")
            artifact = None

        return NewsNodeResult(
            update=build_aggregator_node_update(
                status="success",
                sentiment_summary=aggregation.sentiment_label,
                sentiment_score=aggregation.weighted_score,
                article_count=len(news_items),
                report_id=report_id,
                top_headlines=aggregation.top_headlines,
                artifact=artifact,
            ),
            goto="END",
            summary_message=build_news_summary_message(
                ticker=ticker, result=aggregation
            ),
        )


news_orchestrator = NewsOrchestrator(
    port=news_artifact_port,
    summarize_preview=summarize_news_for_preview,
)
