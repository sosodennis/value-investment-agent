import os

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg_pool import AsyncConnectionPool

from src.utils.logger import get_logger

from .interrupts import ApprovalDetails, HumanApprovalRequest
from .nodes import auditor_node, calculation_node, executor_node
from .nodes.consolidate_research import consolidate_research_node
from .nodes.debate.graph import build_debate_subgraph
from .nodes.financial_news_research.graph import build_financial_news_subgraph
from .nodes.fundamental_analysis.graph import build_fundamental_subgraph
from .nodes.intent_extraction.graph import build_intent_extraction_subgraph
from .nodes.technical_analysis.graph import build_technical_subgraph
from .state import AgentState

logger = get_logger(__name__)


def approval_node(state: AgentState) -> Command:
    """
    Waits for human approval using the interrupt() function.
    """
    logger.info("--- Approval: Requesting human approval ---")

    # Access Pydantic fields
    fundamental = state.get("fundamental_analysis", {})
    if fundamental.get("approved"):
        return Command(goto="calculator")

    audit_passed = False
    audit_messages = []
    audit_output = fundamental.get("audit_output")
    if audit_output:
        # Handle both dict and Pydantic object (due to model_validate)
        if isinstance(audit_output, dict):
            audit_passed = audit_output.get("passed", False)
            audit_messages = audit_output.get("messages", [])
        else:
            audit_passed = audit_output.passed
            audit_messages = audit_output.messages

    # Trigger interrupt. This pauses the graph and returns the user input when resumed.
    interrupt_payload = HumanApprovalRequest(
        details=ApprovalDetails(
            ticker=state.get("ticker"),
            model=fundamental.get("model_type"),
            audit_passed=audit_passed,
            audit_messages=audit_messages,
        )
    )

    ans = interrupt(interrupt_payload.model_dump())
    logger.info(f"--- Approval: Received user input: {ans} ---")

    # When resumed, ans will contain the payload sent from frontend (e.g. { "approved": true })
    # Persist interaction to history
    new_messages = [
        AIMessage(
            content="",
            additional_kwargs={
                "type": "approval_request",
                "data": interrupt_payload.model_dump(),
                "agent_id": "approval",
            },
        ),
        HumanMessage(content="Approved" if ans.get("approved") else "Rejected"),
    ]

    if ans.get("approved"):
        logger.info("✅ Received human approval.")
        return Command(
            update={
                "fundamental_analysis": {"approved": True},
                "messages": new_messages,
                "node_statuses": {"approval": "done", "calculator": "running"},
            },
            goto="calculator",
        )
    else:
        logger.warning("❌ Final approval rejected.")
        return Command(
            update={
                "fundamental_analysis": {"approved": False},
                "messages": new_messages,
                "node_statuses": {"approval": "done"},
            },
            goto=END,
        )


# Helper for initialization
_compiled_graph = None
_saver = None


async def get_graph():
    """Lazy-initialize and return the compiled graph with persistent checkpointer."""
    global _compiled_graph, _saver
    if _compiled_graph is None:
        try:
            # 1. Build Parent Graph
            builder = StateGraph(AgentState)

            # --- Node Definitions ---

            # Intent Extraction Agent
            builder.add_node(
                "intent_agent",
                build_intent_extraction_subgraph(),
                metadata={"agent_id": "intent_extraction"},
            )

            # Fundamental Analysis Agent
            builder.add_node(
                "fundamental_agent",
                build_fundamental_subgraph(),
                metadata={"agent_id": "fundamental_analysis"},
            )

            # Financial News Research Agent
            builder.add_node(
                "news_agent",
                build_financial_news_subgraph(),
                metadata={"agent_id": "financial_news_research"},
            )

            # Technical Analysis Agent
            builder.add_node(
                "technical_agent",
                build_technical_subgraph(),
                metadata={"agent_id": "technical_analysis"},
            )

            # Research Consolidation
            builder.add_node("consolidate_research", consolidate_research_node)

            # Debate Agent
            builder.add_node(
                "debate_agent", build_debate_subgraph(), metadata={"agent_id": "debate"}
            )

            # Core Execution Nodes
            builder.add_node(
                "executor", executor_node, metadata={"agent_id": "executor"}
            )
            builder.add_node(
                "auditor",
                auditor_node,  # Was wrapped in RunnableLambda with hide_stream, but usually fine without if generic
                metadata={"agent_id": "auditor"},
            )
            builder.add_node(
                "approval", approval_node, metadata={"agent_id": "approval"}
            )
            builder.add_node(
                "calculator", calculation_node, metadata={"agent_id": "calculator"}
            )

            # --- Edge Definitions ---

            # 1. Start -> Intent
            builder.add_edge(START, "intent_agent")

            # 2. Intent -> Parallel Research Agents
            builder.add_edge("intent_agent", "fundamental_agent")
            builder.add_edge("intent_agent", "news_agent")
            builder.add_edge("intent_agent", "technical_agent")

            # 3. Parallel Agents -> Consolidate
            builder.add_edge(
                ["fundamental_agent", "news_agent", "technical_agent"],
                "consolidate_research",
            )

            # 4. Consolidate -> Debate
            builder.add_edge("consolidate_research", "debate_agent")

            # 5. Debate -> Executor
            builder.add_edge("debate_agent", "executor")

            # 6. Executor -> Auditor -> Approval
            builder.add_edge("executor", "auditor")
            builder.add_edge("auditor", "approval")

            # 7. Approval -> Calculator -> End
            builder.add_edge("approval", "calculator")
            builder.add_edge("calculator", END)

            # --- Initialize Checkpointer ---
            # Construct DB URI from environment variables
            pg_user = os.environ.get("POSTGRES_USER", "postgres")
            pg_pass = os.environ.get("POSTGRES_PASSWORD", "postgres")
            pg_host = os.environ.get("POSTGRES_HOST", "localhost")
            pg_port = os.environ.get("POSTGRES_PORT", "5432")
            pg_db = os.environ.get("POSTGRES_DB", "langgraph")

            db_uri = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
            logger.info(
                f"--- Graph: Connecting to Postgres at {pg_host}:{pg_port}/{pg_db} ---"
            )

            # Create connection pool
            pool = AsyncConnectionPool(
                conninfo=db_uri, max_size=10, open=False, kwargs={"autocommit": True}
            )
            await pool.open()

            _saver = AsyncPostgresSaver(pool)

            # Ensure tables are created
            await _saver.setup()

            # Compile
            _compiled_graph = builder.compile(checkpointer=_saver)
        except Exception:
            raise

    return _compiled_graph
