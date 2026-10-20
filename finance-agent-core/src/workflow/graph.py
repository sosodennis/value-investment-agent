from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from psycopg_pool import AsyncConnectionPool

from src.agents.debate.entrypoint import build_debate_subgraph
from src.agents.fundamental.entrypoint import build_fundamental_subgraph
from src.agents.intent.entrypoint import build_intent_extraction_graph
from src.agents.news.entrypoint import build_financial_news_subgraph
from src.agents.technical.entrypoint import build_technical_subgraph
from src.shared.kernel.tools.logger import get_logger, log_event

from .nodes.consolidate_research import consolidate_research_node
from .state import AgentState

logger = get_logger(__name__)


@dataclass(frozen=True)
class RootAgentGraphs:
    intent: CompiledStateGraph
    fundamental: CompiledStateGraph
    news: CompiledStateGraph
    technical: CompiledStateGraph
    debate: CompiledStateGraph


def build_root_graph(graphs: RootAgentGraphs) -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node(
        "intent_agent",
        graphs.intent,
        metadata={
            "agent_id": "intent_extraction",
            "agent_scope": "agent",
            "agent_node": "intent_agent",
        },
    )
    builder.add_node(
        "fundamental_agent",
        graphs.fundamental,
        metadata={
            "agent_id": "fundamental_analysis",
            "agent_scope": "agent",
            "agent_node": "fundamental_agent",
        },
    )
    builder.add_node(
        "news_agent",
        graphs.news,
        metadata={
            "agent_id": "financial_news_research",
            "agent_scope": "agent",
            "agent_node": "news_agent",
        },
    )
    builder.add_node(
        "technical_agent",
        graphs.technical,
        metadata={
            "agent_id": "technical_analysis",
            "agent_scope": "agent",
            "agent_node": "technical_agent",
        },
    )
    builder.add_node("consolidate_research", consolidate_research_node)
    builder.add_node(
        "debate_agent",
        graphs.debate,
        metadata={
            "agent_id": "debate",
            "agent_scope": "agent",
            "agent_node": "debate_agent",
        },
    )

    builder.add_edge(START, "intent_agent")
    builder.add_edge("intent_agent", "fundamental_agent")
    builder.add_edge("intent_agent", "news_agent")
    builder.add_edge("intent_agent", "technical_agent")
    builder.add_edge(
        ["fundamental_agent", "news_agent", "technical_agent"],
        "consolidate_research",
    )
    builder.add_edge("consolidate_research", "debate_agent")
    builder.add_edge("debate_agent", END)
    return builder


_compiled_graph: CompiledStateGraph | None = None
_saver: AsyncPostgresSaver | None = None


async def get_graph() -> CompiledStateGraph:
    """Lazy-initialize and return the compiled graph with persistent checkpointer."""
    global _compiled_graph, _saver
    if _compiled_graph is None:
        try:
            graphs = RootAgentGraphs(
                intent=build_intent_extraction_graph(),
                fundamental=build_fundamental_subgraph(),
                news=build_financial_news_subgraph(),
                technical=build_technical_subgraph(),
                debate=build_debate_subgraph(),
            )
            builder = build_root_graph(graphs)

            pg_user = os.environ.get("POSTGRES_USER", "postgres")
            pg_pass = os.environ.get("POSTGRES_PASSWORD", "postgres")
            pg_host = os.environ.get("POSTGRES_HOST", "localhost")
            pg_port = os.environ.get("POSTGRES_PORT", "5432")
            pg_db = os.environ.get("POSTGRES_DB", "langgraph")

            db_uri = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
            log_event(
                logger,
                event="workflow_graph_postgres_connecting",
                message="workflow graph connecting to postgres",
                fields={"host": pg_host, "port": pg_port, "database": pg_db},
            )

            pool = AsyncConnectionPool(
                conninfo=db_uri, max_size=10, open=False, kwargs={"autocommit": True}
            )
            await pool.open()
            _saver = AsyncPostgresSaver(pool)
            await _saver.setup()
            _compiled_graph = builder.compile(checkpointer=_saver)
        except Exception as exc:
            log_event(
                logger,
                event="workflow_graph_build_failed",
                message="workflow graph build failed",
                level=logging.ERROR,
                error_code="WORKFLOW_GRAPH_BUILD_FAILED",
                fields={"exception": str(exc)},
            )
            raise

    return _compiled_graph
