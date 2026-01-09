import json
import logging
import os

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ...state import AgentState
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
from .tools import (
    fetch_clean_text,
    generate_news_id,
    get_source_reliability,
    news_search,
)

logger = logging.getLogger(__name__)

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


def search_node(state: AgentState) -> Command:
    """[Funnel Node 1] Search for recent news snippets."""
    ticker = state.resolved_ticker or state.ticker
    if not ticker:
        logger.warning("Financial News Research: No ticker resolved, skipping.")
        return Command(
            update={"node_statuses": {"financial_news_research": "done"}}, goto=END
        )

    print(f"--- [News Research] Searching news for {ticker} ---")
    try:
        results = news_search(ticker)
    except Exception as e:
        print(f"--- [News Research] news_search CRASHED: {e} ---")
        return Command(
            update={"node_statuses": {"financial_news_research": "done"}}, goto=END
        )

    print(f"--- [News Research] Found {len(results or [])} raw results ---")

    if not results:
        return Command(
            update={
                "financial_news_output": {"ticker": ticker, "news_items": []},
                "node_statuses": {"financial_news_research": "done"},
            },
            goto=END,
        )

    # Format for selector
    formatted_results = "\n---\n".join(
        [
            f"[{i+1}] Source: {r.get('source', 'Unknown')} (Date: {r.get('date', 'N/A')})\nTitle: {r.get('title')}\nSnippet: {r.get('snippet')}"
            for i, r in enumerate(results)
        ]
    )

    return Command(
        update={
            "financial_news_output": {
                "ticker": ticker,
                "raw_results": results,
                "formatted_results": formatted_results,
            },
            "node_statuses": {"financial_news_research": "running"},
        },
        goto="selector_node",
    )


def selector_node(state: AgentState) -> Command:
    """[Funnel Node 2] Filter top 3 relevant articles from snippets."""
    output = state.financial_news_output or {}
    ticker = output.get("ticker")
    formatted_results = output.get("formatted_results")

    print(f"--- [News Research] Selecting top articles for {ticker} ---")

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SELECTOR_SYSTEM_PROMPT),
            ("user", SELECTOR_USER_PROMPT),
        ]
    )

    try:
        chain = prompt | llm
        response = chain.invoke({"ticker": ticker, "search_results": formatted_results})

        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        selection = json.loads(content)
        # Convert 1-based indices from LLM to 0-based
        selected_indices = [int(i) - 1 for i in selection.get("selected_indices", [])]

        # Ensure within bounds
        raw_results = output.get("raw_results", [])
        selected_indices = [i for i in selected_indices if 0 <= i < len(raw_results)]

        # Limit to top 3 if LLM returned too many (funnel safety)
        if not selected_indices:
            logger.warning(
                f"Selector LLM returned no indices for {ticker}. Falling back to top 3."
            )
            selected_indices = [0, 1, 2][: len(raw_results)]

    except Exception as e:
        logger.error(f"Selector node failed for {ticker}: {e}. Falling back to top 3.")
        raw_results = output.get("raw_results", [])
        selected_indices = [0, 1, 2][: len(raw_results)]

    print(
        f"--- [News Research] Completed selection. Selected indices: {selected_indices} ---"
    )
    return Command(
        update={
            "financial_news_output": {**output, "selected_indices": selected_indices},
            "node_statuses": {"financial_news_research": "running"},
        },
        goto="fetch_node",
    )


def fetch_node(state: AgentState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles."""
    output = state.financial_news_output or {}
    raw_results = output.get("raw_results", [])
    selected_indices = output.get("selected_indices", [])

    print(f"--- [News Research] Fetching {len(selected_indices)} articles content ---")

    news_items = []
    for idx in selected_indices:
        if idx >= len(raw_results):
            continue
        res = raw_results[idx]
        url = res.get("link")
        title = res.get("title")

        # Fetch full text
        full_content = fetch_clean_text(url) if url else None

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
            )
            news_items.append(item)
            print(f"--- [News Research] ✅ Created news item for: {title[:50]}... ---")
        except Exception as e:
            print(
                f"--- [News Research] ❌ Failed to create news item for URL {url}: {e} ---"
            )
            logger.error(f"Failed to create FinancialNewsItem: {e}")

    print(
        f"--- [News Research] Completed fetching {len(news_items)} articles content ---"
    )
    # Serialize Pydantic models to dicts for JSON compatibility
    # mode='json' ensures HttpUrl, datetime, etc. are converted to JSON-serializable types (strings)
    news_items_serialized = [item.model_dump(mode="json") for item in news_items]
    return Command(
        update={
            "financial_news_output": {**output, "news_items": news_items_serialized},
            "node_statuses": {"financial_news_research": "running"},
        },
        goto="analyst_node",
    )


def analyst_node(state: AgentState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    output = state.financial_news_output or {}
    ticker = output.get("ticker")
    # news_items are now dicts (serialized from fetch_node)
    news_items: list[dict] = output.get("news_items", [])

    print(f"--- [News Research] Analyzing {len(news_items)} articles for {ticker} ---")

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
            update={"node_statuses": {"financial_news_research": "done"}}, goto=END
        )

    for idx, item in enumerate(news_items):
        try:
            title = item.get("title", "Unknown")
            print(
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
                    print(
                        f"--- [News Research] FinBERT: {finbert_result.label} ({finbert_result.score:.2f}) ---"
                    )

            # Step 2: LLM Analysis (Always Hybrid or Basic fallback)
            if finbert_result:
                # Hybrid mode with FinBERT hints
                analysis = chain_finbert.invoke(
                    {
                        "ticker": ticker,
                        "title": title,
                        "source": source_info.get("name", "Unknown"),
                        "published_at": "N/A",
                        "content": content_to_analyze,
                        "finbert_sentiment": finbert_result.label.upper(),
                        "finbert_confidence": f"{finbert_result.score:.1%}",
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

            print(f"--- [News Research] ✅ Completed analysis for article {idx+1} ---")
        except Exception as e:
            print(
                f"--- [News Research] ❌ Analysis FAILED for article {idx+1}: {e} ---"
            )
            logger.error(f"Analysis failed for {item.get('title', 'Unknown')}: {e}")

    analyzed_count = len([i for i in news_items if i.get("analysis")])
    print(f"--- [News Research] Completed analysis for {analyzed_count} articles ---")

    return Command(
        update={
            "financial_news_output": {**output, "news_items": news_items},
            "node_statuses": {"financial_news_research": "running"},
        },
        goto="aggregator_node",
    )


def aggregator_node(state: AgentState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    output = state.financial_news_output or {}
    ticker = output.get("ticker")
    # news_items are now dicts (serialized from previous nodes)
    news_items: list[dict] = output.get("news_items", [])

    print(f"--- [News Research] Aggregating results for {ticker} ---")

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
                summaries.append(f"- {analysis.get('summary', 'No summary')}")

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
            "financial_news_output": final_output.model_dump(mode="json"),
            "node_statuses": {"financial_news_research": "done", "executor": "running"},
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


async def get_financial_news_research_subgraph():
    """Build and return the financial_news_research subgraph."""
    builder = StateGraph(AgentState)
    builder.add_node("search_node", search_node)
    builder.add_node("selector_node", selector_node)
    builder.add_node("fetch_node", fetch_node)
    builder.add_node("analyst_node", analyst_node)
    builder.add_node("aggregator_node", aggregator_node)

    builder.add_edge(START, "search_node")
    # Transitions are handled by Command(goto=...) in the nodes above.

    return builder.compile()
