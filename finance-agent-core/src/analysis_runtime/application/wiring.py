"""Runtime-owned composition for the analysis workflow and its resources."""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from psycopg_pool import AsyncConnectionPool

from src.agents.debate.entrypoint import build_debate_subgraph
from src.agents.fundamental.entrypoint import build_fundamental_subgraph
from src.agents.intent.entrypoint import build_intent_extraction_graph
from src.agents.news.entrypoint import build_financial_news_subgraph
from src.agents.technical.entrypoint import build_technical_subgraph
from src.analysis_runtime.application.ports import ActivityRepository, OwnerPort
from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.infrastructure.langgraph_runner import LangGraphRunner
from src.analysis_runtime.infrastructure.notifications import PostgresNotificationHub
from src.workflow.graph import RootAgentGraphs, build_root_graph

logger = logging.getLogger(__name__)


async def build_analysis_runtime_service(
    *,
    repository: ActivityRepository,
    owner: OwnerPort,
) -> AnalysisRuntimeService:
    """Create graph storage and notification resources owned by one runtime."""
    pool = AsyncConnectionPool(
        conninfo=_postgres_dsn(),
        max_size=10,
        open=False,
        kwargs={"autocommit": True},
    )
    hub: PostgresNotificationHub | None = None
    try:
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        graph = _build_root_graph(saver)

        hub = PostgresNotificationHub()
        await hub.start()
        return AnalysisRuntimeService(
            repository=repository,
            owner=owner,
            runner=LangGraphRunner(graph, close_graph_resources=pool.close),
            hub=hub,
        )
    except BaseException:
        if hub is not None:
            try:
                await hub.close()
            except Exception:
                logger.exception("analysis notification hub cleanup failed")
        try:
            await pool.close()
        except Exception:
            logger.exception("analysis graph pool cleanup failed")
        raise


def _build_root_graph(saver: AsyncPostgresSaver) -> CompiledStateGraph:
    graphs = RootAgentGraphs(
        intent=build_intent_extraction_graph(),
        fundamental=build_fundamental_subgraph(),
        news=build_financial_news_subgraph(),
        technical=build_technical_subgraph(),
        debate=build_debate_subgraph(),
    )
    return build_root_graph(graphs).compile(checkpointer=saver)


def _postgres_dsn() -> str:
    from src.infrastructure.database import DATABASE_URL

    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
