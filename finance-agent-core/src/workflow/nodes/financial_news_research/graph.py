import asyncio
import json
import os

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.utils.logger import get_logger

from .finbert_service import get_finbert_analyzer
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
    NewsResearchOutput,
    SentimentLabel,
    SourceInfo,
)
from .subgraph_state import (
    FinancialNewsInput,
    FinancialNewsOutput,
    FinancialNewsState,
)
from .tools import (
    generate_news_id,
    get_source_reliability,
    news_search_multi_timeframe,
)

logger = get_logger(__name__)

# --- LLM Shared Config ---
DEFAULT_MODEL = "mistralai/devstral-2512:free"


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0):
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        timeout=60,
        max_retries=2,
    )


# --- Nodes ---


def search_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 1] Search for recent news snippets."""
    # Get ticker from intent_extraction context (primary) or fallback to state.ticker
    ticker = state.intent_extraction.resolved_ticker or state.ticker
    if not ticker:
        logger.warning("Financial News Research: No ticker resolved, skipping.")
        return Command(
            update={
                "current_node": "searching",
                "internal_progress": {"searching": "done"},
            },
            goto=END,
        )

    logger.info(f"--- [News Research] Searching news for {ticker} ---")
    try:
        # Extract company_name from intent_extraction context if available
        company_name = None
        if state.intent_extraction.company_profile:
            company_name = state.intent_extraction.company_profile.get("name")

        # Run async search in sync node
        results = asyncio.run(news_search_multi_timeframe(ticker, company_name))
    except Exception as e:
        logger.error(f"--- [News Research] news_search CRASHED: {e} ---")
        return Command(
            update={
                "current_node": "searching",
                "internal_progress": {"searching": "error"},
            },
            goto=END,
        )

    logger.info(f"--- [News Research] Found {len(results or [])} raw results ---")

    if not results:
        return Command(
            update={
                "financial_news": {"output": {"ticker": ticker, "news_items": []}},
                "current_node": "searching",
                "internal_progress": {"searching": "done"},
            },
            goto=END,
        )

    # Format for selector with clearer metadata including search tag
    formatted_list = []
    for r in results:
        categories = r.get("categories", [r.get("_search_tag", "general")])
        categories_str = ", ".join([c.upper() for c in categories])
        formatted_list.append(f"""
Source: {r.get('source')} | [TAGS: {categories_str}] | Date: {r.get('date')} | Frame: {r.get('_time_frame')}
Title: {r.get('title')}
Snippet: {r.get('snippet')}
URL: {r.get('link')}
--------------------------------------------------
""")
    formatted_results = "".join(formatted_list)

    return Command(
        update={
            "financial_news": {
                "output": {
                    "ticker": ticker,
                    "raw_results": results,
                    "formatted_results": formatted_results,
                }
            },
            "current_node": "search_node",
            "internal_progress": {"search_node": "done", "selector_node": "running"},
        },
        goto="selector_node",
    )


def selector_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 2] Filter top relevant articles using URL-based selection."""
    output = state.financial_news.output or {}
    ticker = output.get("ticker")
    formatted_results = output.get("formatted_results")
    raw_results = output.get("raw_results", [])

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
            # Match URLs back to raw_results indices
            selected_urls = [a.get("url") for a in selected_articles if a.get("url")]

            # Pre-compute URL to index map for O(1) lookup
            # We want the FIRST occurrence index, just like the original loop with 'break'
            url_to_idx = {}
            for idx, r in enumerate(raw_results):
                url = r.get("link")
                if url and url not in url_to_idx:
                    url_to_idx[url] = idx

            for url in selected_urls:
                if url in url_to_idx:
                    selected_indices.append(url_to_idx[url])
        else:
            # Case where LLM didn't return the key at all - fallback
            logger.warning(
                f"--- [News Research] Selector returned no 'selected_articles' key for {ticker}. Falling back to top 3."
            )
            if raw_results:
                selected_indices = [0, 1, 2][: len(raw_results)]

    except Exception as e:
        logger.error(f"Selector node failed for {ticker}: {e}. Falling back to top 3.")
        selected_indices = [0, 1, 2][: len(raw_results)]

    # Limit to top 5 for funnel safety
    selected_indices = list(dict.fromkeys(selected_indices))[:10]

    logger.info(
        f"--- [News Research] Completed selection. Selected indices: {selected_indices} ---"
    )
    return Command(
        update={
            "financial_news": {
                "output": {**output, "selected_indices": selected_indices}
            },
            "current_node": "selector_node",
            "internal_progress": {"selector_node": "done", "fetch_node": "running"},
        },
        goto="fetch_node",
    )


def fetch_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles (async parallel)."""
    output = state.financial_news.output or {}
    raw_results = output.get("raw_results", [])
    selected_indices = output.get("selected_indices", [])

    logger.info(
        f"--- [News Research] Fetching {len(selected_indices)} articles content ---"
    )

    # Build list of articles to fetch
    articles_to_fetch = []
    for idx in selected_indices:
        if idx >= len(raw_results):
            continue
        res = raw_results[idx]
        articles_to_fetch.append(res)

    # Async fetch all articles in parallel
    async def fetch_all():
        from .tools import fetch_clean_text_async

        tasks = [
            fetch_clean_text_async(res.get("link"))
            if res.get("link")
            else asyncio.coroutine(lambda: None)()
            for res in articles_to_fetch
        ]
        return await asyncio.gather(*tasks)

    try:
        full_contents = asyncio.run(fetch_all())
    except Exception as e:
        logger.error(f"Async fetch failed: {e}. Falling back to empty contents.")
        full_contents = [None] * len(articles_to_fetch)

    # Build news items
    news_items = []
    for i, res in enumerate(articles_to_fetch):
        url = res.get("link")
        title = res.get("title")
        full_content = full_contents[i]

        # Parse date if available
        published_at = None
        date_str = res.get("date")
        if date_str:
            try:
                from datetime import datetime

                # DDGS returns ISO format e.g. 2026-01-06T15:00:00+00:00
                published_at = datetime.fromisoformat(date_str)
            except Exception:
                pass

        try:
            item = FinancialNewsItem(
                id=generate_news_id(url, title),
                url=url,
                title=title,
                snippet=res.get("snippet", ""),
                full_content=full_content,
                published_at=published_at,
                source=SourceInfo(
                    name=res.get("source")
                    or (title.split(" - ")[-1] if " - " in title else "Unknown"),
                    domain=url.split("//")[-1].split("/")[0] if url else "unknown",
                    reliability_score=get_source_reliability(url) if url else 0.5,
                ),
                categories=res.get("categories", []),
            )
            news_items.append(item)
            logger.info(
                f"--- [News Research] ✅ Created news item for: {title[:50]}... ---"
            )
        except Exception as e:
            logger.error(
                f"--- [News Research] ❌ Failed to create news item for URL {url}: {e} ---"
            )
            logger.error(f"Failed to create FinancialNewsItem: {e}")

    logger.info(
        f"--- [News Research] Completed fetching {len(news_items)} articles content ---"
    )
    # Serialize Pydantic models to dicts for JSON compatibility
    # mode='json' ensures HttpUrl, datetime, etc. are converted to JSON-serializable types (strings)
    news_items_serialized = [item.model_dump(mode="json") for item in news_items]
    return Command(
        update={
            "financial_news": {
                "output": {**output, "news_items": news_items_serialized}
            },
            "current_node": "fetch_node",
            "internal_progress": {"fetch_node": "done", "analyst_node": "running"},
        },
        goto="analyst_node",
    )


def analyst_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    output = state.financial_news.output or {}
    ticker = output.get("ticker")
    # news_items are now dicts (serialized from fetch_node)
    news_items: list[dict] = output.get("news_items", [])

    logger.info(
        f"--- [News Research] Analyzing {len(news_items)} articles for {ticker} ---"
    )

    # Initialize FinBERT Service
    finbert_analyzer = get_finbert_analyzer()

    llm = get_llm()

    # Pre-create both chains for flexibility
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
            },
            goto=END,
        )

    for idx, item in enumerate(news_items):
        try:
            title = item.get("title", "Unknown")
            logger.info(
                f"--- [News Research] Analyzing article {idx+1}/{len(news_items)}: {title[:50]}... ---"
            )
            # Analyze using full content if available, else fallback to snippet
            content_to_analyze = item.get("full_content") or item.get("snippet", "")
            source_info = item.get("source", {})

            # Step 1: Local FinBERT Pre-Analysis
            finbert_result = None
            if finbert_analyzer.is_available():
                finbert_result = finbert_analyzer.analyze(content_to_analyze)
                if finbert_result:
                    item["finbert_analysis"] = finbert_result.to_dict()
                    logger.debug(
                        f"--- [News Research] FinBERT: {finbert_result.label} ({finbert_result.score:.2f}) ---"
                    )

            # Get Search Tags for prompt
            categories = item.get("categories", ["general"])
            search_tag_str = ", ".join([c.upper() for c in categories])

            # Step 2: LLM Analysis (Always Hybrid or Basic fallback)
            if finbert_result:
                # Hybrid mode with FinBERT hints
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
                # Basic fallback mode (No FinBERT data)
                analysis = chain_basic.invoke(
                    {
                        "ticker": ticker,
                        "title": title,
                        "source": source_info.get("name", "Unknown"),
                        "published_at": "N/A",
                        "content": content_to_analyze,
                    }
                )

            # Serialize AIAnalysis to dict before storing
            item["analysis"] = (
                analysis.model_dump() if hasattr(analysis, "model_dump") else analysis
            )
            item["analysis"]["source"] = "llm"

            logger.info(
                f"--- [News Research] ✅ Completed analysis for article {idx+1} ---"
            )
        except Exception as e:
            logger.error(
                f"--- [News Research] ❌ Analysis FAILED for article {idx+1}: {e} ---"
            )
            logger.error(f"Analysis failed for {item.get('title', 'Unknown')}: {e}")

    analyzed_count = len([i for i in news_items if i.get("analysis")])
    logger.info(
        f"--- [News Research] Completed analysis for {analyzed_count} articles ---"
    )

    return Command(
        update={
            "financial_news": {"output": {**output, "news_items": news_items}},
            "current_node": "analyst_node",
            "internal_progress": {"analyst_node": "done", "aggregator_node": "running"},
        },
        goto="aggregator_node",
    )


def aggregator_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    output = state.financial_news.output or {}
    ticker = output.get("ticker")
    # news_items are now dicts (serialized from previous nodes)
    news_items: list[dict] = output.get("news_items", [])

    logger.info(f"--- [News Research] Aggregating results for {ticker} ---")

    if not news_items:
        summary_text = "No detailed news analysis available."
        overall_sentiment = SentimentLabel.NEUTRAL
        weighted_score = 0.0
        all_themes = []
    else:
        # Weighted sentiment calculation
        total_weight = 0.0
        weighted_score_sum = 0.0
        themes = set()
        summaries = []

        for item in news_items:
            analysis = item.get("analysis")
            if analysis:
                # Weight = Reliability * Impact?
                # Simple weight for now: reliability
                source_info = item.get("source", {})
                weight = source_info.get("reliability_score", 0.5)
                total_weight += weight
                weighted_score_sum += analysis.get("sentiment_score", 0) * weight

                key_event = analysis.get("key_event")
                if key_event:
                    themes.add(key_event)

                # Summary with key facts count
                facts_count = len(analysis.get("key_facts", []))
                summaries.append(
                    f"- {analysis.get('summary', 'No summary')} ({facts_count} key facts)"
                )

        weighted_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0

        if weighted_score > 0.3:
            overall_sentiment = SentimentLabel.BULLISH
        elif weighted_score < -0.3:
            overall_sentiment = SentimentLabel.BEARISH
        else:
            overall_sentiment = SentimentLabel.NEUTRAL

        summary_text = "\n".join(summaries)
        all_themes = list(themes)

    final_output = NewsResearchOutput(
        ticker=ticker,
        news_items=news_items,
        overall_sentiment=overall_sentiment,
        sentiment_score=round(weighted_score, 2),
        key_themes=all_themes,
    )

    return Command(
        update={
            # mode='json' ensures HttpUrl, datetime, Enums are serialized as strings for msgpack/checkpoint
            "financial_news": {"output": final_output.model_dump(mode="json")},
            "current_node": "aggregator_node",
            "internal_progress": {"aggregator_node": "done"},
            # [BSP Fix] Emit status immediately to bypass LangGraph's sync barrier
            # allowing the UI to update without waiting for parallel branches (FA/TA)
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


def build_financial_news_subgraph():
    """Build and return the financial_news_research subgraph."""
    builder = StateGraph(
        FinancialNewsState, input=FinancialNewsInput, output=FinancialNewsOutput
    )
    builder.add_node(
        "search_node", search_node, metadata={"agent_id": "financial_news_research"}
    )
    builder.add_node(
        "selector_node",
        RunnableLambda(selector_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_node(
        "fetch_node", fetch_node, metadata={"agent_id": "financial_news_research"}
    )
    builder.add_node(
        "analyst_node",
        RunnableLambda(analyst_node).with_config(tags=["hide_stream"]),
        metadata={"agent_id": "financial_news_research"},
    )
    builder.add_node(
        "aggregator_node",
        aggregator_node,
        metadata={"agent_id": "financial_news_research"},
    )

    builder.add_edge(START, "search_node")
    # Transitions are handled by Command(goto=...) in the nodes above.

    return builder.compile()
