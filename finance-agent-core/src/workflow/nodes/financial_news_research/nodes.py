import asyncio
import json
import time

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END
from langgraph.types import Command

from src.common.tools.llm import get_llm
from src.common.tools.logger import get_logger
from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.services.artifact_manager import artifact_manager

from .mappers import summarize_news_for_preview
from .prompts import (
    ANALYST_SYSTEM_PROMPT,
    ANALYST_USER_PROMPT_BASIC,
    ANALYST_USER_PROMPT_WITH_FINBERT,
    SELECTOR_SYSTEM_PROMPT,
    SELECTOR_USER_PROMPT,
)
from .schemas import FinancialNewsSuccess
from .structures import (
    AIAnalysis,
    FinancialNewsItem,
    NewsResearchOutput,
    SentimentLabel,
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
        return Command(
            update={
                "current_node": "search_node",
                "internal_progress": {"search_node": "done"},
            },
            goto=END,
        )

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
        return Command(
            update={
                "current_node": "search_node",
                "internal_progress": {"search_node": "error"},
                "node_statuses": {"financial_news_research": "error"},
                "error_logs": [
                    {
                        "node": "search_node",
                        "error": f"Search failed: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    logger.info(f"--- [News Research] Found {len(results or [])} raw results ---")

    if not results:
        return Command(
            update={
                "news_items": [],
                "current_node": "search_node",
                "internal_progress": {"search_node": "done"},
            },
            goto=END,
        )

    cleaned_results = []
    for r in results:
        cleaned_results.append(
            {
                "title": r.get("title", ""),
                "source": r.get("source", ""),
                "snippet": r.get("snippet", ""),
                "link": r.get("link", ""),
                "date": r.get("date", ""),
                "categories": r.get("categories", [r.get("_search_tag", "general")]),
            }
        )

    # Format for selector (using cleaned_results)
    formatted_list = []
    for r in cleaned_results:
        categories = r.get("categories", [])
        categories_str = ", ".join([c.upper() for c in categories])
        formatted_list.append(f"""
Source: {r.get('source')} | [TAGS: {categories_str}] | Date: {r.get('date')}
Title: {r.get('title')}
Snippet: {r.get('snippet')}
URL: {r.get('link')}
--------------------------------------------------
""")
    formatted_results = "".join(formatted_list)

    # Save search results to Artifact Store
    search_data = {
        "raw_results": cleaned_results,
        "formatted_results": formatted_results,
    }
    timestamp = int(time.time())
    try:
        search_artifact_id = await artifact_manager.save_artifact(
            data=search_data,
            artifact_type="search_results",
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
    artifact = AgentOutputArtifact(
        summary=f"News Research: Found {len(cleaned_results)} articles for {ticker}",
        preview=preview,
        reference=None,
    )

    return Command(
        update={
            "financial_news_research": {
                "artifact": artifact,
                "article_count": len(cleaned_results),
                "search_artifact_id": search_artifact_id,
            },
            "current_node": "search_node",
            "internal_progress": {"search_node": "done", "selector_node": "running"},
            "node_statuses": {"financial_news_research": "running"},
        },
        goto="selector_node",
    )


async def selector_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 2] Filter top relevant articles using URL-based selection."""
    ctx = state.get("financial_news_research", {})
    search_artifact_id = ctx.get("search_artifact_id")

    formatted_results = ""
    raw_results = []
    is_degraded = False
    error_msg = ""

    if search_artifact_id:
        try:
            artifact = await artifact_manager.get_artifact(search_artifact_id)
            if artifact:
                search_data = artifact.data
                formatted_results = search_data.get("formatted_results", "")
                raw_results = search_data.get("raw_results", [])
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

    selected_indices = []
    try:
        chain = prompt | llm
        response = chain.invoke({"ticker": ticker, "search_results": formatted_results})

        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        selection_data = json.loads(content)
        selected_articles = selection_data.get("selected_articles")

        if selected_articles is not None:
            selected_urls = [a.get("url") for a in selected_articles if a.get("url")]
            url_to_idx = {
                r.get("link"): idx for idx, r in enumerate(raw_results) if r.get("link")
            }
            for url in selected_urls:
                if url in url_to_idx:
                    selected_indices.append(url_to_idx[url])
        else:
            logger.warning(
                f"--- [News Research] Selector returned no 'selected_articles' key for {ticker}. Falling back to top 3."
            )
            if raw_results:
                selected_indices = [0, 1, 2][: len(raw_results)]

    except Exception as e:
        logger.error(
            f"Selector node failed for {ticker}: {e}. Falling back to top 3.",
            exc_info=True,
        )
        selected_indices = [0, 1, 2][: len(raw_results)]
        is_degraded = True
        error_msg = str(e)

    selected_indices = list(dict.fromkeys(selected_indices))[:10]

    logger.info(
        f"--- [News Research] Completed selection. Selected indices: {selected_indices} ---"
    )

    timestamp = int(time.time())
    selection_artifact_id = None
    try:
        selection_data = {"selected_indices": selected_indices}
        selection_artifact_id = await artifact_manager.save_artifact(
            data=selection_data,
            artifact_type="news_selection",
            key_prefix=f"selection_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save selection artifact: {e}")
        is_degraded = True
        if not error_msg:
            error_msg = f"Failed to save selection artifact: {str(e)}"

    update_payload = {
        "financial_news_research": {"selection_artifact_id": selection_artifact_id},
        "current_node": "selector_node",
        "internal_progress": {"selector_node": "done", "fetch_node": "running"},
    }

    if is_degraded:
        update_payload["node_statuses"] = {"financial_news_research": "degraded"}
        update_payload["error_logs"] = [
            {
                "node": "selector_node",
                "error": f"Selection failed: {error_msg}. Falling back to top articles."
                if error_msg and "Selection failed" not in error_msg
                else (
                    error_msg
                    or "Selection failed due to an unknown error. Falling back to top articles."
                ),
                "severity": "warning",
            }
        ]

    return Command(
        update=update_payload,
        goto="fetch_node",
    )


async def fetch_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles (async parallel)."""
    ctx = state.get("financial_news_research", {})
    search_id = ctx.get("search_artifact_id")
    selection_id = ctx.get("selection_artifact_id")

    raw_results = []
    selected_indices = []
    article_errors = []

    if search_id and selection_id:
        try:
            s_art = await artifact_manager.get_artifact(search_id)
            sel_art = await artifact_manager.get_artifact(selection_id)
            if s_art:
                raw_results = s_art.data.get("raw_results", [])
            if sel_art:
                selected_indices = sel_art.data.get("selected_indices", [])
        except Exception as e:
            logger.error(f"Failed to retrieve fetch artifacts: {e}")
            article_errors.append(
                f"Failed to retrieve search/selection artifacts: {str(e)}"
            )

    logger.info(
        f"--- [News Research] Fetching {len(selected_indices)} articles content ---"
    )

    articles_to_fetch = []
    for idx in selected_indices:
        if idx >= len(raw_results):
            continue
        articles_to_fetch.append(raw_results[idx])

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

    for i, res in enumerate(articles_to_fetch):
        url = res.get("link")
        title = res.get("title")
        full_content = full_contents[i]

        content_id = None
        if full_content:
            try:
                content_id = await artifact_manager.save_artifact(
                    data={"full_text": full_content, "title": title, "url": url},
                    artifact_type="news_article",
                    key_prefix=f"news_{ticker}_{timestamp}_{i}",
                )
            except Exception as e:
                logger.error(f"Failed to save artifact for {url}: {e}")

        published_at = None
        date_str = res.get("date")
        if date_str:
            try:
                from datetime import datetime

                published_at = datetime.fromisoformat(date_str)
            except Exception:
                pass

        try:
            item = FinancialNewsItem(
                id=generate_news_id(url, title),
                url=url,
                title=title,
                snippet=res.get("snippet", ""),
                full_content=None,
                published_at=published_at,
                source=SourceInfo(
                    name=res.get("source")
                    or (title.split(" - ")[-1] if " - " in title else "Unknown"),
                    domain=url.split("//")[-1].split("/")[0] if url else "unknown",
                    reliability_score=get_source_reliability(url) if url else 0.5,
                ),
                categories=res.get("categories", []),
            )
            item_dict = item.model_dump(mode="json")
            item_dict["content_id"] = content_id
            item_dict["full_content"] = full_content
            news_items.append(item_dict)
        except Exception as e:
            logger.error(
                f"--- [News Research] ❌ Failed to create news item for URL {url}: {e} ---"
            )

    news_items_id = None
    try:
        news_items_id = await artifact_manager.save_artifact(
            data={"news_items": news_items},
            artifact_type="news_items_list",
            key_prefix=f"news_items_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save news items list artifact: {e}")

    final_status = "running"
    if article_errors:
        final_status = "degraded"

    update_payload = {
        "financial_news_research": {"news_items_artifact_id": news_items_id},
        "current_node": "fetch_node",
        "internal_progress": {"fetch_node": "done", "analyst_node": "running"},
        "node_statuses": {"financial_news_research": final_status},
    }

    if article_errors:
        update_payload["error_logs"] = [
            {
                "node": "fetch_node",
                "error": article_errors[0],
                "severity": "warning",
            }
        ]

    return Command(update=update_payload, goto="analyst_node")


async def analyst_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    ctx = state.get("financial_news_research", {})
    news_items_id = ctx.get("news_items_artifact_id")

    news_items: list[dict] = []
    article_errors = []

    if news_items_id:
        try:
            art = await artifact_manager.get_artifact(news_items_id)
            if art:
                news_items = art.data.get("news_items", [])
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
        chain_basic = prompt_basic | llm.with_structured_output(AIAnalysis)
        chain_finbert = prompt_finbert | llm.with_structured_output(AIAnalysis)
    except Exception as e:
        logger.error(f"Failed to create chains for {ticker}: {e}")
        return Command(
            update={
                "current_node": "analyst_node",
                "internal_progress": {"analyst_node": "error"},
                "node_statuses": {"financial_news_research": "error"},
                "error_logs": [
                    {
                        "node": "analyst_node",
                        "error": f"Failed to create analysis chains: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto=END,
        )

    for idx, item in enumerate(news_items):
        try:
            title = item.get("title", "Unknown")
            content_to_analyze = item.get("snippet", "")

            content_id = item.get("content_id")
            if content_id:
                try:
                    full_art = await artifact_manager.get_artifact(content_id)
                    if full_art and full_art.data.get("full_text"):
                        content_to_analyze = full_art.data.get("full_text")
                except Exception as ex:
                    logger.warning(f"Could not load full content for analysis: {ex}")

            source_info = item.get("source", {})
            finbert_result = None
            if finbert_analyzer.is_available():
                finbert_result = await asyncio.to_thread(
                    finbert_analyzer.analyze, content_to_analyze
                )
                if finbert_result:
                    item["finbert_analysis"] = finbert_result.to_dict()

            categories = item.get("categories", ["general"])
            search_tag_str = ", ".join([c.upper() for c in categories])

            if finbert_result:
                analysis = chain_finbert.invoke(
                    {
                        "ticker": ticker,
                        "title": title,
                        "source": source_info.get("name", "Unknown"),
                        "search_tag": search_tag_str,
                        "published_at": "N/A",
                        "content": content_to_analyze,
                        "finbert_sentiment": finbert_result.label.upper(),
                        "finbert_confidence": f"{finbert_result.score:.1%}",
                        "finbert_has_numbers": "Yes"
                        if finbert_result.has_numbers
                        else "No",
                    }
                )
            else:
                analysis = chain_basic.invoke(
                    {
                        "ticker": ticker,
                        "title": title,
                        "source": source_info.get("name", "Unknown"),
                        "published_at": "N/A",
                        "content": content_to_analyze,
                    }
                )

            item["analysis"] = (
                analysis.model_dump() if hasattr(analysis, "model_dump") else analysis
            )
            item["analysis"]["source"] = "llm"

        except Exception as e:
            logger.error(
                f"--- [News Research] ❌ Analysis FAILED for article {idx+1}: {e} ---",
                exc_info=True,
            )
            article_errors.append(
                f"Analysis failed for {item.get('title', 'Unknown')}: {str(e)}"
            )

    timestamp = int(time.time())
    try:
        news_items_id = await artifact_manager.save_artifact(
            data={"news_items": news_items},
            artifact_type="news_items_list",
            key_prefix=f"news_items_analyzed_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save analyzed news items artifact: {e}")
        news_items_id = None

    final_status = "running"
    if article_errors:
        final_status = "degraded"

    update_payload = {
        "financial_news_research": {"news_items_artifact_id": news_items_id},
        "current_node": "analyst_node",
        "internal_progress": {"analyst_node": "done", "aggregator_node": "running"},
        "node_statuses": {"financial_news_research": final_status},
    }

    if article_errors:
        update_payload["error_logs"] = [
            {
                "node": "analyst_node",
                "error": f"Failed to analyze {len(article_errors)} articles.",
                "severity": "warning",
            }
        ]

    return Command(update=update_payload, goto="aggregator_node")


async def aggregator_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    ctx = state.get("financial_news_research", {})
    news_items_id = ctx.get("news_items_artifact_id")

    news_items: list[dict] = []
    if news_items_id:
        try:
            art = await artifact_manager.get_artifact(news_items_id)
            if art:
                news_items = art.data.get("news_items", [])
        except Exception as e:
            logger.error(f"Failed to retrieve news items for aggregation: {e}")

    ticker = state.get("ticker", "UNKNOWN")
    logger.info(f"--- [News Research] Aggregating results for {ticker} ---")

    summary_text = ""
    overall_sentiment = SentimentLabel.NEUTRAL
    weighted_score = 0.0
    all_themes = []

    if news_items:
        total_weight = 0.0
        weighted_score_sum = 0.0
        themes = set()
        summaries = []

        for item in news_items:
            analysis = item.get("analysis")
            if analysis:
                source_info = item.get("source", {})
                weight = source_info.get("reliability_score", 0.5)
                total_weight += weight
                weighted_score_sum += analysis.get("sentiment_score", 0) * weight

                key_theme = analysis.get("key_event")
                if key_theme:
                    themes.add(key_theme)

                facts_count = len(analysis.get("key_facts", []))
                summaries.append(
                    f"- {analysis.get('summary', 'No summary')} ({facts_count} key facts)"
                )

        weighted_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0
        if weighted_score > 0.3:
            overall_sentiment = SentimentLabel.BULLISH
        elif weighted_score < -0.3:
            overall_sentiment = SentimentLabel.BEARISH

        summary_text = "\n".join(summaries)
        all_themes = list(themes)

    final_output = NewsResearchOutput(
        ticker=ticker,
        news_items=news_items,
        overall_sentiment=overall_sentiment,
        sentiment_score=round(weighted_score, 2),
        key_themes=all_themes,
    )

    report_data = FinancialNewsSuccess(
        **final_output.model_dump(mode="json")
    ).model_dump(mode="json")

    timestamp = int(time.time())
    try:
        report_id = await artifact_manager.save_artifact(
            data=report_data,
            artifact_type="news_analysis_report",
            key_prefix=f"news_report_{ticker}_{timestamp}",
        )
    except Exception as e:
        logger.error(f"Failed to save final report artifact: {e}")
        report_id = None

    try:
        preview = summarize_news_for_preview(final_output.model_dump(), news_items)
        reference = None
        if report_id:
            reference = ArtifactReference(
                artifact_id=report_id,
                download_url=f"/api/artifacts/{report_id}",
                type="news_analysis_report",
            )

        artifact = AgentOutputArtifact(
            summary=f"News Research: {overall_sentiment.value.upper()} ({weighted_score:.2f})",
            preview=preview,
            reference=reference,
        )
    except Exception as e:
        logger.error(f"Failed to generate news artifact: {e}")
        artifact = None

    news_update = {
        "status": "success",
        "sentiment_summary": overall_sentiment.value,
        "sentiment_score": round(weighted_score, 2),
        "article_count": len(news_items),
        "report_id": report_id,
        "top_headlines": [
            item.get("title") for item in news_items[:3] if item.get("title")
        ],
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
                    content=f"### News Research: {ticker}\n\n**Overall Sentiment:** {overall_sentiment.value.upper()} ({final_output.sentiment_score})\n\n**Analysis Summaries:**\n{summary_text}\n\n**Themes:** {', '.join(all_themes) or 'N/A'}",
                    additional_kwargs={
                        "type": "text",
                        "agent_id": "financial_news_research",
                    },
                )
            ],
        },
        goto=END,
    )
