from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from langchain_core.messages import AIMessage

from src.agents.news.application.analysis_service import (
    analyze_news_items,
    build_analysis_chains,
)
from src.agents.news.application.fetch_service import (
    build_articles_to_fetch,
    build_cleaned_search_results,
    build_news_items_from_fetch_results,
)
from src.agents.news.application.ports import (
    LLMLike,
    NewsItemFactoryLike,
    SourceFactoryLike,
)
from src.agents.news.application.selection_service import (
    format_selector_input,
    run_selector_with_resilience,
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
from src.agents.news.data.ports import NewsArtifactPort
from src.agents.news.domain.services import (
    aggregate_news_items,
    build_news_summary_message,
)
from src.agents.news.interface.contracts import parse_news_artifact_model
from src.agents.news.interface.parsers import (
    parse_news_items,
    parse_news_search_result_items,
)
from src.agents.news.interface.prompt_renderers import (
    build_analyst_chat_prompts,
    build_selector_chat_prompt,
)
from src.agents.news.interface.serializers import build_search_progress_preview
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_ARTIFACT_JSON,
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


@dataclass(frozen=True)
class NewsNodeResult:
    update: dict[str, object]
    goto: str


@dataclass(frozen=True)
class NewsOrchestrator:
    port: NewsArtifactPort
    summarize_preview: Callable[[JSONObject, list[JSONObject] | None], JSONObject]
    build_news_report_payload: Callable[[str, list[JSONObject], object], JSONObject]
    build_output_artifact: Callable[
        [str, JSONObject, str | None], dict[str, object] | None
    ]

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
            log_event(
                logger,
                event="news_search_missing_ticker",
                message="news search skipped due to missing ticker",
                level=logging.WARNING,
                error_code="NEWS_TICKER_MISSING",
            )
            return NewsNodeResult(
                update=build_search_node_no_ticker_update(), goto="END"
            )

        log_event(
            logger,
            event="news_search_started",
            message="news search started",
            fields={"ticker": ticker},
        )
        try:
            company_name = company_name_from_state(state)
            results = await news_search_multi_timeframe_fn(ticker, company_name)
        except Exception as exc:
            log_event(
                logger,
                event="news_search_failed",
                message="news search failed",
                level=logging.ERROR,
                error_code="NEWS_SEARCH_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
            return NewsNodeResult(
                update=build_search_node_error_update(str(exc)),
                goto="END",
            )

        result_count = len(results or [])
        log_event(
            logger,
            event="news_search_completed",
            message="news search completed",
            fields={"ticker": ticker, "raw_result_count": result_count},
        )
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
            log_event(
                logger,
                event="news_search_artifact_saved",
                message="news search artifact saved",
                fields={"ticker": ticker, "search_artifact_id": search_artifact_id},
            )
        except Exception as exc:
            log_event(
                logger,
                event="news_search_artifact_save_failed",
                message="failed to save news search artifact",
                level=logging.ERROR,
                error_code="NEWS_SEARCH_ARTIFACT_SAVE_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
            search_artifact_id = None

        preview = build_search_progress_preview(
            article_count=len(cleaned_results),
            cleaned_results=cleaned_results,
        )
        artifact = self.build_output_artifact(
            f"News Research: Found {len(cleaned_results)} articles for {ticker}",
            preview,
            None,
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
            parsed_results = parse_news_search_result_items(
                list(raw_results),
                context="news selector search results",
            )
            raw_results = [item.model_dump(mode="json") for item in parsed_results]
        except Exception as exc:
            log_event(
                logger,
                event="news_selector_context_load_failed",
                message="failed to load selector search context",
                level=logging.ERROR,
                error_code="NEWS_SELECTOR_CONTEXT_LOAD_FAILED",
                fields={
                    "exception": str(exc),
                    "search_artifact_id": search_artifact_id,
                },
            )

        ticker = resolved_ticker_from_state(state)

        log_event(
            logger,
            event="news_selector_started",
            message="news selector started",
            fields={"ticker": ticker, "raw_result_count": len(raw_results)},
        )
        llm = get_llm_fn()
        prompt = build_selector_chat_prompt(
            system_prompt=selector_system_prompt,
            user_prompt=selector_user_prompt,
        )
        chain = prompt | llm
        selector_result = run_selector_with_resilience(
            chain=chain,
            ticker=ticker,
            formatted_results=formatted_results,
            raw_results=raw_results,
        )
        selected_indices = selector_result.selected_indices
        if selector_result.is_degraded:
            is_degraded = True
            error_msg = selector_result.error_message

        log_event(
            logger,
            event="news_selector_completed",
            message="news selector completed",
            fields={
                "ticker": ticker,
                "selected_indices": selected_indices,
                "selected_count": len(selected_indices),
                "is_degraded": is_degraded,
            },
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
            log_event(
                logger,
                event="news_selector_artifact_save_failed",
                message="failed to save selector artifact",
                level=logging.ERROR,
                error_code="NEWS_SELECTOR_ARTIFACT_SAVE_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
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
        item_factory: NewsItemFactoryLike,
        source_factory: SourceFactoryLike,
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
            log_event(
                logger,
                event="news_fetch_context_load_failed",
                message="failed to load fetch context",
                level=logging.ERROR,
                error_code="NEWS_FETCH_CONTEXT_LOAD_FAILED",
                fields={
                    "search_artifact_id": search_id,
                    "selection_artifact_id": selection_id,
                    "exception": str(exc),
                },
            )
            article_errors.append(
                f"Failed to retrieve search/selection artifacts: {str(exc)}"
            )

        log_event(
            logger,
            event="news_fetch_started",
            message="news fetch started",
            fields={"selected_count": len(selected_indices)},
        )

        parsed_results = parse_news_search_result_items(
            list(raw_results),
            context="news fetch search results",
        )
        articles_to_fetch = build_articles_to_fetch(parsed_results, selected_indices)

        async def fetch_all() -> list[str | None]:
            tasks = [
                fetch_clean_text_async_fn(res.link)
                if res.link
                else asyncio.sleep(0, result=None)
                for res in articles_to_fetch
            ]
            return await asyncio.gather(*tasks)

        try:
            full_contents = await fetch_all()
        except Exception as exc:
            log_event(
                logger,
                event="news_fetch_async_failed",
                message="news fetch async failed; entering degraded mode",
                level=logging.ERROR,
                error_code="NEWS_FETCH_ASYNC_FAILED",
                fields={
                    "exception": str(exc),
                    "selected_count": len(articles_to_fetch),
                },
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
            log_event(
                logger,
                event="news_fetch_artifact_save_failed",
                message="failed to save fetched news items artifact",
                level=logging.ERROR,
                error_code="NEWS_FETCH_ARTIFACT_SAVE_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )

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
            parsed_news_items = parse_news_items(
                list(news_items),
                context="news analyst items",
            )
            news_items = [item.model_dump(mode="json") for item in parsed_news_items]
        except Exception as exc:
            log_event(
                logger,
                event="news_analyst_items_load_failed",
                message="failed to load news items for analyst",
                level=logging.ERROR,
                error_code="NEWS_ANALYST_ITEMS_LOAD_FAILED",
                fields={"news_items_artifact_id": news_items_id, "exception": str(exc)},
            )
            article_errors.append(f"Failed to retrieve news items: {str(exc)}")

        ticker = resolved_ticker_from_state(state)

        log_event(
            logger,
            event="news_analyst_started",
            message="news analyst started",
            fields={"ticker": ticker, "article_count": len(news_items)},
        )

        finbert_analyzer = get_finbert_analyzer_fn()
        llm = get_llm_fn()

        prompt_basic, prompt_finbert = build_analyst_chat_prompts(
            system_prompt=analyst_system_prompt,
            user_prompt_basic=analyst_user_prompt_basic,
            user_prompt_with_finbert=analyst_user_prompt_with_finbert,
        )

        try:
            analysis_chains = build_analysis_chains(
                llm=llm,
                prompt_basic=prompt_basic,
                prompt_finbert=prompt_finbert,
                analysis_model_type=analysis_model_type,
            )
        except Exception as exc:
            log_event(
                logger,
                event="news_analyst_chain_build_failed",
                message="failed to build analyst chains",
                level=logging.ERROR,
                error_code="NEWS_ANALYST_CHAIN_BUILD_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
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
            log_event(
                logger,
                event="news_analyst_artifact_save_failed",
                message="failed to save analyzed news items artifact",
                level=logging.ERROR,
                error_code="NEWS_ANALYST_ARTIFACT_SAVE_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
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
    ) -> NewsNodeResult:
        news_items_id = news_items_artifact_id_from_state(state)

        news_items: list[dict] = []
        try:
            news_items = await self.port.load_news_items_data(news_items_id)
            parsed_news_items = parse_news_items(
                list(news_items),
                context="news aggregator items",
            )
            news_items = [item.model_dump(mode="json") for item in parsed_news_items]
        except Exception as exc:
            log_event(
                logger,
                event="news_aggregator_items_load_failed",
                message="failed to load news items for aggregation",
                level=logging.ERROR,
                error_code="NEWS_AGGREGATOR_ITEMS_LOAD_FAILED",
                fields={"news_items_artifact_id": news_items_id, "exception": str(exc)},
            )

        news_item_entities = self.port.project_news_item_entities(news_items)
        ticker = aggregator_ticker_from_state(state)
        log_event(
            logger,
            event="news_aggregator_started",
            message="news aggregator started",
            fields={"ticker": ticker, "news_items_count": len(news_items)},
        )

        try:
            aggregation = aggregate_news_items(news_item_entities, ticker=ticker)
            report_payload = self.build_news_report_payload(
                ticker=ticker,
                news_items=news_items,
                aggregation=aggregation,
            )
            report_data = parse_news_artifact_model(report_payload)
        except Exception as exc:
            log_boundary_event(
                logger,
                node="news.aggregator",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
                error_code="NEWS_REPORT_PAYLOAD_BUILD_FAILED",
                state=state,
                detail={
                    "exception": str(exc),
                    "ticker": ticker,
                    "news_items_count": len(news_items),
                },
                level=logging.ERROR,
            )
            return NewsNodeResult(
                update={
                    "financial_news_research": {
                        "status": "error",
                        "sentiment_summary": "unknown",
                        "sentiment_score": 0.0,
                        "article_count": len(news_items),
                        "report_id": None,
                        "top_headlines": [],
                    },
                    "current_node": "aggregator_node",
                    "internal_progress": {"aggregator_node": "error"},
                    "node_statuses": {"financial_news_research": "error"},
                    "error_logs": [
                        {
                            "node": "aggregator_node",
                            "error": f"Failed to build news report payload: {str(exc)}",
                            "severity": "error",
                            "error_code": "NEWS_REPORT_PAYLOAD_BUILD_FAILED",
                            "contract_kind": CONTRACT_KIND_ARTIFACT_JSON,
                            "artifact_id": None,
                            "diagnostics": build_replay_diagnostics(
                                state, node="news.aggregator"
                            ),
                        }
                    ],
                },
                goto="END",
            )

        timestamp = int(time.time())
        try:
            report_id = await self.port.save_news_report(
                data=report_data,
                produced_by="financial_news_research.aggregator_node",
                key_prefix=f"news_report_{ticker}_{timestamp}",
            )
        except Exception as exc:
            log_event(
                logger,
                event="news_aggregator_report_save_failed",
                message="failed to save final news report artifact",
                level=logging.ERROR,
                error_code="NEWS_REPORT_SAVE_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
            report_id = None
            log_boundary_event(
                logger,
                node="news.aggregator",
                artifact_id=None,
                contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
                error_code="NEWS_REPORT_SAVE_FAILED",
                state=state,
                detail={"exception": str(exc), "ticker": ticker},
                level=logging.ERROR,
            )

        try:
            preview = self.summarize_preview(report_payload, news_items)
            artifact = self.build_output_artifact(
                f"News Research: {aggregation.sentiment_label.upper()} ({aggregation.weighted_score:.2f})",
                preview,
                report_id,
            )
        except Exception as exc:
            log_event(
                logger,
                event="news_aggregator_output_artifact_failed",
                message="failed to build news output artifact",
                level=logging.ERROR,
                error_code="NEWS_OUTPUT_ARTIFACT_FAILED",
                fields={"ticker": ticker, "exception": str(exc)},
            )
            artifact = None

        log_boundary_event(
            logger,
            node="news.aggregator",
            artifact_id=report_id,
            contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
            error_code="OK",
            state=state,
            detail={
                "ticker": ticker,
                "news_items_count": len(news_items),
                "sentiment_label": aggregation.sentiment_label,
            },
        )
        log_event(
            logger,
            event="news_aggregator_completed",
            message="news aggregator completed",
            fields={
                "ticker": ticker,
                "news_items_count": len(news_items),
                "sentiment_label": aggregation.sentiment_label,
                "sentiment_score": aggregation.weighted_score,
                "report_id": report_id,
            },
        )
        summary_message = build_news_summary_message(ticker=ticker, result=aggregation)
        update = build_aggregator_node_update(
            status="success",
            sentiment_summary=aggregation.sentiment_label,
            sentiment_score=aggregation.weighted_score,
            article_count=len(news_items),
            report_id=report_id,
            top_headlines=aggregation.top_headlines,
            artifact=artifact,
        )
        update["messages"] = [
            AIMessage(
                content=summary_message,
                additional_kwargs={
                    "type": "text",
                    "agent_id": "financial_news_research",
                },
            )
        ]
        return NewsNodeResult(
            update=update,
            goto="END",
        )
