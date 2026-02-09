import os

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from src.common.tools.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DDGS_REGION = os.getenv("DDGS_REGION", "us-en")
DEFAULT_DDGS_BACKEND = os.getenv("DDGS_BACKEND", "duckduckgo")


def web_search(query: str) -> str:
    """
    Optimized web search for financial entity resolution.
    Fetches more results to capture dual-class stocks (e.g., GOOG vs GOOGL).
    """
    try:
        # 1. Inject "share classes tickers" if query looks like a ticker search
        if "ticker" in query.lower() or "stock" in query.lower():
            if "share class" not in query.lower():
                query += " share classes tickers"

        logger.info(f"Executing optimized search query: {query}")

        # 2. Init Wrapper with more results
        # NOTE: Force a valid region and a stable backend to avoid
        # wikipedia/grokipedia DNS failures (e.g., wt.wikipedia.org).
        search = DuckDuckGoSearchAPIWrapper(
            max_results=7,
            time="y",
            region=DEFAULT_DDGS_REGION,
            backend=DEFAULT_DDGS_BACKEND,
        )

        # 3. Execute search
        results = search.results(query, max_results=7)

        if not results:
            return "No search results found."

        # 4. Format output
        formatted_output = []
        for i, res in enumerate(results, 1):
            title = res.get("title", "No Title")
            snippet = res.get("snippet", "No Snippet")
            formatted_output.append(f"[{i}] Source: {title}\nContent: {snippet}\n")

        return "\n---\n".join(formatted_output)

    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"Web search currently unavailable. Error: {str(e)}"
