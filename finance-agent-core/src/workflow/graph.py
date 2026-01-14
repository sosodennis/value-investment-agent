from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.utils.logger import get_logger

from .nodes import (
    auditor_node,
    calculation_node,
    executor_node,
    get_financial_news_research_subgraph,
)
from .nodes.debate import get_debate_subgraph
from .nodes.fundamental_analysis.graph import get_fundamental_analysis_subgraph
from .state import AgentState

logger = get_logger(__name__)


def approval_node(state: AgentState) -> Command:
    """
    Waits for human approval using the interrupt() function.
    """
    logger.info("--- Approval: Requesting human approval ---")

    # Access Pydantic fields
    if state.approved:
        return Command(goto="calculator")

    audit_passed = False
    audit_messages = []
    if state.audit_output:
        audit_passed = state.audit_output.passed
        audit_messages = state.audit_output.messages

    from .interrupts import ApprovalDetails, HumanApprovalRequest

    # Trigger interrupt. This pauses the graph and returns the user input when resumed.
    interrupt_payload = HumanApprovalRequest(
        details=ApprovalDetails(
            ticker=state.ticker,
            model=state.model_type,
            audit_passed=audit_passed,
            audit_messages=audit_messages,
        )
    )

    ans = interrupt(interrupt_payload.model_dump())
    logger.info(f"--- Approval: Received user input: {ans} ---")

    # When resumed, ans will contain the payload sent from frontend (e.g. { "approved": true })
    from langchain_core.messages import AIMessage, HumanMessage

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
                "approved": True,
                "messages": new_messages,
                "node_statuses": {"approval": "done", "calculator": "running"},
            },
            goto="calculator",
        )
    else:
        logger.warning("❌ Final approval rejected.")
        return Command(
            update={
                "approved": False,
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
        # 1. Initialize Subgraphs
        fundamental_analysis_graph = await get_fundamental_analysis_subgraph()
        financial_news_research_graph = await get_financial_news_research_subgraph()
        debate_graph = await get_debate_subgraph()

        # 2. Build Parent Graph
        builder = StateGraph(AgentState)
        builder.add_node("fundamental_analysis", fundamental_analysis_graph)
        builder.add_node("financial_news_research", financial_news_research_graph)
        builder.add_node("debate", debate_graph)
        builder.add_node("executor", executor_node)
        builder.add_node("auditor", auditor_node)
        builder.add_node("approval", approval_node)
        builder.add_node("calculator", calculation_node)

        builder.add_edge(START, "fundamental_analysis")
        builder.add_edge("fundamental_analysis", "financial_news_research")
        builder.add_edge("financial_news_research", "debate")
        builder.add_edge("debate", "executor")
        builder.add_edge("executor", "auditor")

        builder.add_edge("auditor", "approval")
        builder.add_edge("approval", "calculator")
        builder.add_edge("calculator", END)

        # 3. Initialize Checkpointer
        import os

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        # Construct DB URI from environment variables
        pg_user = os.environ.get("POSTGRES_USER", "postgres")
        pg_pass = os.environ.get("POSTGRES_PASSWORD", "postgres")
        pg_host = os.environ.get("POSTGRES_HOST", "localhost")
        pg_port = os.environ.get("POSTGRES_PORT", "5432")
        pg_db = os.environ.get("POSTGRES_DB", "langgraph")

        db_uri = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
        logger.info(f"--- Graph: Connecting to Postgres at {pg_host}:{pg_port}/{pg_db} ---")

        # Create connection pool
        pool = AsyncConnectionPool(
            conninfo=db_uri, max_size=10, open=False, kwargs={"autocommit": True}
        )
        await pool.open()

        _saver = AsyncPostgresSaver(pool)

        # Ensure tables are created
        await _saver.setup()

        # 4. Compile
        _compiled_graph = builder.compile(checkpointer=_saver)

    return _compiled_graph
