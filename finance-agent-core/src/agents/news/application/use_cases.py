from __future__ import annotations

from src.agents.news.application import (
    analysis_service,
    fetch_service,
    selection_service,
    state_updates,
)
from src.agents.news.domain.entities import NewsItemEntity
from src.agents.news.domain.models import NewsAggregationResult
from src.agents.news.domain.services import (
    aggregate_news_items as domain_aggregate_news_items,
)
from src.agents.news.domain.services import (
    build_news_summary_message as domain_build_news_summary_message,
)

build_analysis_chain_payload = analysis_service.build_analysis_chain_payload
AnalysisChains = analysis_service.AnalysisChains
AnalystExecutionResult = analysis_service.AnalystExecutionResult
analyze_news_items = analysis_service.analyze_news_items
build_analysis_chains = analysis_service.build_analysis_chains
run_analysis_with_fallback = analysis_service.run_analysis_with_fallback

FetchBuildResult = fetch_service.FetchBuildResult
build_articles_to_fetch = fetch_service.build_articles_to_fetch
build_cleaned_search_results = fetch_service.build_cleaned_search_results
build_news_item_payload = fetch_service.build_news_item_payload
build_news_items_from_fetch_results = fetch_service.build_news_items_from_fetch_results
parse_published_at = fetch_service.parse_published_at

SelectorExecutionResult = selection_service.SelectorExecutionResult
build_selector_fallback_indices = selection_service.build_selector_fallback_indices
format_selector_input = selection_service.format_selector_input
normalize_selected_indices = selection_service.normalize_selected_indices
run_selector_with_fallback = selection_service.run_selector_with_fallback

build_fetch_node_update = state_updates.build_fetch_node_update
build_analyst_node_update = state_updates.build_analyst_node_update
build_search_node_no_ticker_update = state_updates.build_search_node_no_ticker_update
build_search_node_error_update = state_updates.build_search_node_error_update
build_search_node_empty_update = state_updates.build_search_node_empty_update
build_search_node_success_update = state_updates.build_search_node_success_update
build_selector_node_update = state_updates.build_selector_node_update
build_analyst_chain_error_update = state_updates.build_analyst_chain_error_update


def aggregate_news_items(
    news_items: list[NewsItemEntity], *, ticker: str
) -> NewsAggregationResult:
    return domain_aggregate_news_items(news_items, ticker=ticker)


def build_news_summary_message(*, ticker: str, result: NewsAggregationResult) -> str:
    return domain_build_news_summary_message(ticker=ticker, result=result)
