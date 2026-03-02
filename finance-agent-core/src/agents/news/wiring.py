from __future__ import annotations

from src.agents.news.application.factory import (
    NewsWorkflowDependencies,
    NewsWorkflowRunner,
    build_news_orchestrator,
    build_news_workflow_runner,
)
from src.agents.news.application.ports import FetchContentResult
from src.agents.news.infrastructure.artifacts.news_artifact_repository import (
    build_default_news_artifact_repository,
)
from src.agents.news.infrastructure.content_fetch import fetch_clean_text_async
from src.agents.news.infrastructure.ids import generate_news_id
from src.agents.news.infrastructure.search import news_search_multi_timeframe
from src.agents.news.infrastructure.sentiment import get_finbert_analyzer
from src.agents.news.infrastructure.source_reliability import get_source_reliability
from src.infrastructure.llm.provider import get_llm
from src.shared.kernel.types import JSONObject


async def _news_search_multi_timeframe(
    ticker: str, company_name: str | None
) -> list[JSONObject]:
    return await news_search_multi_timeframe(ticker, company_name)


def _get_llm():
    return get_llm()


async def _fetch_clean_text_async(url: str) -> FetchContentResult:
    return await fetch_clean_text_async(url)


def _generate_news_id(url: str | None, title: str | None) -> str:
    return generate_news_id(url or "", title or "")


def _get_source_reliability(url: str) -> float:
    return get_source_reliability(url)


def _get_finbert_analyzer():
    return get_finbert_analyzer()


def build_default_news_workflow_runner() -> NewsWorkflowRunner:
    repository = build_default_news_artifact_repository()
    orchestrator = build_news_orchestrator(port=repository)
    return build_news_workflow_runner(
        orchestrator=orchestrator,
        deps=NewsWorkflowDependencies(
            news_search_multi_timeframe_fn=_news_search_multi_timeframe,
            get_llm_fn=_get_llm,
            fetch_clean_text_async_fn=_fetch_clean_text_async,
            generate_news_id_fn=_generate_news_id,
            get_source_reliability_fn=_get_source_reliability,
            get_finbert_analyzer_fn=_get_finbert_analyzer,
        ),
    )


_news_workflow_runner: NewsWorkflowRunner | None = None


def get_news_workflow_runner() -> NewsWorkflowRunner:
    global _news_workflow_runner
    if _news_workflow_runner is None:
        _news_workflow_runner = build_default_news_workflow_runner()
    return _news_workflow_runner


__all__ = [
    "NewsWorkflowRunner",
    "build_default_news_workflow_runner",
    "get_news_workflow_runner",
]
