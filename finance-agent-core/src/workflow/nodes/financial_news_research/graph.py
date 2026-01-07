"""
Financial News Research Sub-graph implementation.
"""

import os

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ...state import AgentState
from ..fundamental_analysis.tools import web_search
from .prompts import NEWS_SUMMARY_SYSTEM_PROMPT, NEWS_SUMMARY_USER_PROMPT
from .structures import NewsResearchOutput


def news_research_node(state: AgentState) -> Command:
    """Search for recent news and summarize using LLM."""
    ticker = state.resolved_ticker or state.ticker
    if not ticker:
        print("--- Financial News Research: No ticker resolved, skipping ---")
        return Command(
            update={
                "node_statuses": {"financial_news_research": "done"},
            },
            goto=END,
        )

    print(f"--- Financial News Research: Searching news for {ticker} ---")
    query = f"recent news and developments for {ticker} stock"
    search_results = web_search(query)

    # --- LLM Summarization ---
    try:
        llm = ChatOpenAI(
            model="xiaomi/mimo-v2-flash:free",
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            timeout=30,
            max_retries=2,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", NEWS_SUMMARY_SYSTEM_PROMPT),
                ("user", NEWS_SUMMARY_USER_PROMPT),
            ]
        )

        chain = prompt | llm.with_structured_output(NewsResearchOutput)
        summary_output = chain.invoke(
            {"ticker": ticker, "search_results": search_results}
        )

        output = {
            "ticker": ticker,
            "news_summary": summary_output.summary,
            "sentiment": summary_output.sentiment,
            "key_themes": summary_output.key_themes,
            "raw_results": search_results,
        }
    except Exception as e:
        print(f"⚠️  LLM News Summary failed: {e}. Using fallback.")
        output = {
            "ticker": ticker,
            "news_summary": "Financial news research completed (LLM summary failed).",
            "raw_results": search_results,
        }

    return Command(
        update={
            "financial_news_output": output,
            "node_statuses": {"financial_news_research": "done", "executor": "running"},
            "messages": [
                AIMessage(
                    content=f"Completed news research for {ticker}.\n\n**Summary:** {output.get('news_summary', '')}\n\n**Sentiment:** {output.get('sentiment', 'N/A')}",
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
    builder.add_node("news_research", news_research_node)
    builder.add_edge(START, "news_research")
    return builder.compile()
