from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from src.agents.news.application.orchestrator import NewsOrchestrator
from src.agents.news.data.clients import (
    fetch_clean_text_async,
    generate_news_id,
    get_finbert_analyzer,
    get_source_reliability,
    news_search_multi_timeframe,
)
from src.agents.news.data.ports import news_artifact_port
from src.agents.news.interface.contracts import (
    AIAnalysisModel,
    FinancialNewsItemModel,
    SourceInfoModel,
)
from src.agents.news.interface.mappers import summarize_news_for_preview
from src.agents.news.interface.prompts import (
    ANALYST_SYSTEM_PROMPT,
    ANALYST_USER_PROMPT_BASIC,
    ANALYST_USER_PROMPT_WITH_FINBERT,
    SELECTOR_SYSTEM_PROMPT,
    SELECTOR_USER_PROMPT,
)
from src.agents.news.interface.serializers import build_news_report_payload
from src.infrastructure.llm.provider import get_llm
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
)
from src.shared.kernel.tools.logger import get_logger

from .subgraph_state import FinancialNewsState

logger = get_logger(__name__)


def _build_news_output_artifact(
    summary: str, preview: dict[str, object], report_id: str | None
) -> dict[str, object] | None:
    reference = None
    if report_id:
        reference = ArtifactReference(
            artifact_id=report_id,
            download_url=f"/api/artifacts/{report_id}",
            type=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        )
    return build_artifact_payload(
        kind=OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
        summary=summary,
        preview=preview,
        reference=reference,
    )


news_orchestrator = NewsOrchestrator(
    port=news_artifact_port,
    summarize_preview=summarize_news_for_preview,
    build_news_report_payload=build_news_report_payload,
    build_output_artifact=_build_news_output_artifact,
)


def _resolve_goto(goto: str) -> str:
    return END if goto == "END" else goto


async def search_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 1] Search for recent news snippets."""
    result = await news_orchestrator.run_search(
        state,
        news_search_multi_timeframe_fn=news_search_multi_timeframe,
    )
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def selector_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 2] Filter top relevant articles using URL-based selection."""
    result = await news_orchestrator.run_selector(
        state,
        get_llm_fn=get_llm,
        selector_system_prompt=SELECTOR_SYSTEM_PROMPT,
        selector_user_prompt=SELECTOR_USER_PROMPT,
    )
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def fetch_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 3] Fetch and clean full text for selected articles (async parallel)."""
    result = await news_orchestrator.run_fetch(
        state,
        fetch_clean_text_async_fn=fetch_clean_text_async,
        generate_news_id_fn=generate_news_id,
        get_source_reliability_fn=get_source_reliability,
        item_factory=FinancialNewsItemModel,
        source_factory=SourceInfoModel,
    )
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def analyst_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 4] Deep analysis per article."""
    result = await news_orchestrator.run_analyst(
        state,
        get_llm_fn=get_llm,
        get_finbert_analyzer_fn=get_finbert_analyzer,
        analyst_system_prompt=ANALYST_SYSTEM_PROMPT,
        analyst_user_prompt_basic=ANALYST_USER_PROMPT_BASIC,
        analyst_user_prompt_with_finbert=ANALYST_USER_PROMPT_WITH_FINBERT,
        analysis_model_type=AIAnalysisModel,
    )
    return Command(update=result.update, goto=_resolve_goto(result.goto))


async def aggregator_node(state: FinancialNewsState) -> Command:
    """[Funnel Node 5] Aggregate results and update state."""
    result = await news_orchestrator.run_aggregator(state)

    update = dict(result.update)
    summary_message = result.summary_message
    if summary_message:
        update["messages"] = [
            AIMessage(
                content=summary_message,
                additional_kwargs={
                    "type": "text",
                    "agent_id": "financial_news_research",
                },
            )
        ]

    return Command(update=update, goto=_resolve_goto(result.goto))
