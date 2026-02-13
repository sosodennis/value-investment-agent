import asyncio
import time

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END
from langgraph.types import Command

from src.agents.news.application.services import (
    aggregate_news_items,
    analyze_news_items,
    build_analysis_chains,
    build_analyst_chain_error_update,
    build_analyst_node_update,
    build_articles_to_fetch,
    build_cleaned_search_results,
    build_fetch_node_update,
    build_news_items_from_fetch_results,
    build_news_summary_message,
    build_search_node_empty_update,
    build_search_node_error_update,
    build_search_node_no_ticker_update,
    build_search_node_success_update,
    build_selector_node_update,
    format_selector_input,
    run_selector_with_fallback,
)
from src.agents.news.data.ports import news_artifact_port
from src.agents.news.interface.mappers import summarize_news_for_preview
from src.common.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
)
from src.common.tools.llm import get_llm
from src.common.tools.logger import get_logger
from src.interface.canonical_serializers import canonicalize_news_artifact_data
from src.interface.schemas import ArtifactReference, build_artifact_payload

from .prompts import (
    ANALYST_SYSTEM_PROMPT,
    ANALYST_USER_PROMPT_BASIC,
    ANALYST_USER_PROMPT_WITH_FINBERT,
    SELECTOR_SYSTEM_PROMPT,
    SELECTOR_USER_PROMPT,
)
from .structures import (
    AIAnalysis,
    FinancialNewsItem,
    SourceInfo,
)
from .subgraph_state import (
    FinancialNewsState,
)
from .tools import (
    generate_news_id,
    get_finbert_analyzer,
    get_source_reliability,
    news_search_multi_timeframe,
)

logger = get_logger(__name__)


async def search_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 1] Search for recent news snippets."""
    # Get ticker from intent_extraction context (primary) or fallback to state.ticker
    intent_ctx = state.get("intent_extraction", {})
    ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")
    if not ticker:
        logger.warning("Financial News Research: No ticker resolved, skipping.")
        return Command(update=build_search_node_no_ticker_update(), goto=END)

    logger.info(f"--- [News Research] Searching news for {ticker} ---")
    try:
        # Extract company_name from intent_extraction context if available
        company_name = None
        profile = intent_ctx.get("company_profile")
        if profile:
            company_name = profile.get("name")

        # Run async search in sync node
        results = await news_search_multi_timeframe(ticker, company_name)
    except Exception as e:
        logger.error(f"--- [News Research] news_search CRASHED: {e} ---", exc_info=True)
        return Command(update=build_search_node_error_update(str(e)), goto=END)

    logger.info(f"--- [News Research] Found {len(results or [])} raw results ---")

    if not results:
        return Command(update=build_search_node_empty_update(), goto=END)

    cleaned_results = build_cleaned_search_results(results)
    formatted_results = format_selector_input(cleaned_results)

    # Save search results to Artifact Store
    search_data = {
        "raw_results": cleaned_results,
        "formatted_results": formatted_results,
    }
    timestamp = int(time.time())
    try:
        search_artifact_id = await news_artifact_port.save_search_results(
            data=search_data,
            produced_by="financial_news_research.search_node",
            key_prefix=f"search_{ticker}_{timestamp}",
        )
        logger.info(
            f"--- [News Research] Saved search artifact (ID: {search_artifact_id}) ---"
        )
    except Exception as e:
        logger.error(f"Failed to save search artifact: {e}")
        search_artifact_id = None

    # [NEW] Emit preliminary artifact
    preview = {
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

    return Command(
        update=build_search_node_success_update(
            artifact=artifact,
            article_count=len(cleaned_results),
            search_artifact_id=search_artifact_id,
        ),
        goto="selector_node",
    )


async def selector_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 2] Filter top relevant articles using URL-based selection."""
    ctx = state.get("financial_news_research", {})
    search_artifact_id = ctx.get("search_artifact_id")

    formatted_results = ""
    raw_results: list[dict[str, object]] = []
    is_degraded = False
    error_msg = ""

    try:
        formatted_results, raw_results = await news_artifact_port.load_search_context(
            search_artifact_id
        )
    except Exception as e:
        logger.error(f"Failed to retrieve search artifact: {e}")

    intent_ctx = state.get("intent_extraction", {})
    ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")

    logger.info(f"--- [News Research] Selecting top articles for {ticker} ---")

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SELECTOR_SYSTEM_PROMPT),
            ("user", SELECTOR_USER_PROMPT),
        ]
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
        selection_data = {"selected_indices": selected_indices}
        selection_artifact_id = await news_artifact_port.save_news_selection(
            data=selection_data,
            produced_by="financial_news_research.selector_node",
            key_prefix=f"selection_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save selection artifact: {e}")
        is_degraded = True
        if not error_msg:
            error_msg = f"Failed to save selection artifact: {str(e)}"

    update_payload = build_selector_node_update(
        selection_artifact_id=selection_artifact_id,
        is_degraded=is_degraded,
        error_message=error_msg,
    )

    return Command(
        update=update_payload,
        goto="fetch_node",
    )


async def fetch_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles (async parallel)."""
    ctx = state.get("financial_news_research", {})
    search_id = ctx.get("search_artifact_id")
    selection_id = ctx.get("selection_artifact_id")

    raw_results: list[dict[str, object]] = []
    selected_indices: list[int] = []
    article_errors = []

    try:
        raw_results, selected_indices = await news_artifact_port.load_fetch_context(
            search_id, selection_id
        )
    except Exception as e:
        logger.error(f"Failed to retrieve fetch artifacts: {e}")
        article_errors.append(
            f"Failed to retrieve search/selection artifacts: {str(e)}"
        )

    logger.info(
        f"--- [News Research] Fetching {len(selected_indices)} articles content ---"
    )

    articles_to_fetch = build_articles_to_fetch(raw_results, selected_indices)

    async def fetch_all():
        from .tools import fetch_clean_text_async

        tasks = [
            fetch_clean_text_async(res.get("link"))
            if res.get("link")
            else asyncio.sleep(0, result=None)
            for res in articles_to_fetch
        ]
        return await asyncio.gather(*tasks)

    try:
        full_contents = await fetch_all()
    except Exception as e:
        logger.error(
            f"Async fetch failed: {e}. Falling back to empty contents.", exc_info=True
        )
        full_contents = [None] * len(articles_to_fetch)
        article_errors.append(f"Content fetch partially failed: {str(e)}")

    news_items = []
    intent_ctx = state.get("intent_extraction", {})
    ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")
    timestamp = int(time.time())

    fetch_result = await build_news_items_from_fetch_results(
        articles_to_fetch=articles_to_fetch,
        full_contents=full_contents,
        ticker=ticker,
        timestamp=timestamp,
        port=news_artifact_port,
        generate_news_id_fn=generate_news_id,
        get_source_reliability_fn=get_source_reliability,
        item_factory=FinancialNewsItem,
        source_factory=SourceInfo,
    )
    news_items = fetch_result.news_items
    article_errors.extend(fetch_result.article_errors)

    news_items_id = None
    try:
        news_items_id = await news_artifact_port.save_news_items(
            data={"news_items": news_items},
            produced_by="financial_news_research.fetch_node",
            key_prefix=f"news_items_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save news items list artifact: {e}")

    update_payload = build_fetch_node_update(
        news_items_id=news_items_id, article_errors=article_errors
    )

    return Command(update=update_payload, goto="analyst_node")


async def analyst_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    ctx = state.get("financial_news_research", {})
    news_items_id = ctx.get("news_items_artifact_id")

    news_items: list[dict] = []
    article_errors = []

    try:
        news_items = await news_artifact_port.load_news_items_data(news_items_id)
    except Exception as e:
        logger.error(f"Failed to retrieve news items: {e}")
        article_errors.append(f"Failed to retrieve news items: {str(e)}")

    intent_ctx = state.get("intent_extraction", {})
    ticker = intent_ctx.get("resolved_ticker") or state.get("ticker")

    logger.info(
        f"--- [News Research] Analyzing {len(news_items)} articles for {ticker} ---"
    )

    finbert_analyzer = get_finbert_analyzer()
    llm = get_llm()

    prompt_basic = ChatPromptTemplate.from_messages(
        [
            ("system", ANALYST_SYSTEM_PROMPT),
            ("user", ANALYST_USER_PROMPT_BASIC),
        ]
    )
    prompt_finbert = ChatPromptTemplate.from_messages(
        [
            ("system", ANALYST_SYSTEM_PROMPT),
            ("user", ANALYST_USER_PROMPT_WITH_FINBERT),
        ]
    )

    try:
        analysis_chains = build_analysis_chains(
            llm=llm,
            prompt_basic=prompt_basic,
            prompt_finbert=prompt_finbert,
            analysis_model_type=AIAnalysis,
        )
    except Exception as e:
        logger.error(f"Failed to create chains for {ticker}: {e}")
        return Command(update=build_analyst_chain_error_update(str(e)), goto=END)

    analyst_result = await analyze_news_items(
        news_items=news_items,
        ticker=ticker,
        port=news_artifact_port,
        finbert_analyzer=finbert_analyzer,
        chains=analysis_chains,
    )
    news_items = analyst_result.news_items
    article_errors.extend(analyst_result.article_errors)

    timestamp = int(time.time())
    try:
        news_items_id = await news_artifact_port.save_news_items(
            data={"news_items": news_items},
            produced_by="financial_news_research.analyst_node",
            key_prefix=f"news_items_analyzed_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save analyzed news items artifact: {e}")
        news_items_id = None

    update_payload = build_analyst_node_update(
        news_items_id=news_items_id, article_errors=article_errors
    )

    return Command(update=update_payload, goto="aggregator_node")


async def aggregator_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    ctx = state.get("financial_news_research", {})
    news_items_id = ctx.get("news_items_artifact_id")

    news_items: list[dict] = []
    try:
        news_items = await news_artifact_port.load_news_items_data(news_items_id)
    except Exception as e:
        logger.error(f"Failed to retrieve news items for aggregation: {e}")

    ticker = state.get("ticker", "UNKNOWN")
    logger.info(f"--- [News Research] Aggregating results for {ticker} ---")

    aggregation = aggregate_news_items(news_items, ticker=ticker)
    report_data = canonicalize_news_artifact_data(aggregation.report_payload)

    timestamp = int(time.time())
    try:
        report_id = await news_artifact_port.save_news_report(
            data=report_data,
            produced_by="financial_news_research.aggregator_node",
            key_prefix=f"news_report_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save final report artifact: {e}")
        report_id = None

    try:
        preview = summarize_news_for_preview(aggregation.report_payload, news_items)
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
    except Exception as e:
        logger.error(f"Failed to generate news artifact: {e}")
        artifact = None

    news_update = {
        "status": "success",
        "sentiment_summary": aggregation.sentiment_label,
        "sentiment_score": aggregation.weighted_score,
        "article_count": len(news_items),
        "report_id": report_id,
        "top_headlines": aggregation.top_headlines,
    }
    if artifact:
        news_update["artifact"] = artifact

    return Command(
        update={
            "financial_news_research": news_update,
            "current_node": "aggregator_node",
            "internal_progress": {"aggregator_node": "done"},
            "node_statuses": {"financial_news_research": "done"},
            "messages": [
                AIMessage(
                    content=build_news_summary_message(
                        ticker=ticker, result=aggregation
                    ),
                    additional_kwargs={
                        "type": "text",
                        "agent_id": "financial_news_research",
                    },
                )
            ],
        },
        goto=END,
    )
