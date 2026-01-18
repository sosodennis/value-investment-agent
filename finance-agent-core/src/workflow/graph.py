from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.utils.logger import get_logger

from .nodes import (
    auditor_node,
    calculation_node,
    executor_node,
)
from .nodes.consolidate_research import consolidate_research_node
from .state import AgentState

logger = get_logger(__name__)


def approval_node(state: AgentState) -> Command:
    """
    Waits for human approval using the interrupt() function.
    """
    logger.info("--- Approval: Requesting human approval ---")

    # Access Pydantic fields
    if state.fundamental.approved:
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
                "fundamental": {"approved": True},
                "messages": new_messages,
                "node_statuses": {"approval": "done", "calculator": "running"},
            },
            goto="calculator",
        )
    else:
        logger.warning("❌ Final approval rejected.")
        return Command(
            update={
                "fundamental": {"approved": False},
                "messages": new_messages,
                "node_statuses": {"approval": "done"},
            },
            goto=END,
        )


# ============================================================================
# Wrapper Nodes for Isolated Subgraph State (LangGraph Best Practice)
# ============================================================================
# These wrapper nodes transform state between parent AgentState and isolated
# subgraph states, preventing stale status updates from subgraph completions.


async def debate_wrapper_node(state: AgentState) -> dict:
    """
    Wrapper for debate subgraph with isolated state.

    Transforms parent AgentState → DebateSubgraphState → parent updates.
    This prevents stale node_statuses from polluting the parent graph.
    """
    try:
        logger.info("=== [DEBUG] debate_wrapper_node: Starting ===")
        logger.info(f"[DEBUG] debate_wrapper_node: state type = {type(state)}")
        logger.info(f"[DEBUG] debate_wrapper_node: state.ticker = {state.ticker}")

        from src.workflow.nodes.debate.graph import get_debate_subgraph
        from src.workflow.nodes.debate.subgraph_state import DebateSubgraphState

        logger.info("[DEBUG] debate_wrapper_node: Imports successful")

        # 1. Transform parent state → subgraph input (Pydantic BaseModel)
        logger.info("[DEBUG] debate_wrapper_node: Creating DebateSubgraphState...")
        subgraph_input = DebateSubgraphState(
            ticker=state.ticker,
            intent_extraction=state.intent_extraction,  # Needed for resolved_ticker
            debate=state.debate,
            fundamental=state.fundamental,
            financial_news=state.financial_news,
            internal_progress={},  # Initialize internal tracking
            current_node="",
        )
        logger.info(
            f"[DEBUG] debate_wrapper_node: DebateSubgraphState created, type = {type(subgraph_input)}"
        )

        # 2. Invoke isolated subgraph
        logger.info("[DEBUG] debate_wrapper_node: Getting debate subgraph...")
        debate_graph = await get_debate_subgraph()
        logger.info("[DEBUG] debate_wrapper_node: Invoking debate subgraph...")
        result = await debate_graph.ainvoke(subgraph_input.model_dump())
        logger.info("[DEBUG] debate_wrapper_node: Debate subgraph completed")

        # 3. Transform subgraph output → parent state
        # ONLY update what changed - explicit and clean!
        return_value = {
            "debate": result["debate"],
            "current_node": result.get("current_node", "debate"),
            "node_statuses": {
                "debate": "done",  # Clean, explicit status update
                "executor": "running",  # Next node in parent graph
            },
        }
        return return_value

    except Exception as e:
        logger.error(
            f"❌ [DEBUG] debate_wrapper_node: ERROR - {type(e).__name__}: {str(e)}"
        )
        import traceback

        logger.error(
            f"[DEBUG] debate_wrapper_node: Traceback:\n{traceback.format_exc()}"
        )
        raise


def map_model_to_skill(model_name: str | None) -> str:
    """
    Maps a valuation model name or enum value to a valid SkillRegistry key.

    Currently supports:
    - 'bank' (for DDM/Bank models)
    - 'saas' (default, for all DCF/Growth models using FCFF engine)
    """
    if not model_name:
        return "saas"

    name_lower = str(model_name).lower()
    if any(x in name_lower for x in ["bank", "ddm"]):
        return "bank"

    return "saas"


async def fundamental_analysis_wrapper_node(state: AgentState) -> dict:
    """
    Wrapper for fundamental analysis subgraph with isolated state.

    Transforms parent AgentState → FundamentalAnalysisSubgraphState → parent updates.
    """
    from src.workflow.nodes.fundamental_analysis.subgraph_state import (
        FundamentalAnalysisSubgraphState,
    )

    subgraph_input = FundamentalAnalysisSubgraphState(
        ticker=state.ticker,
        intent_extraction=state.intent_extraction,
        fundamental=state.fundamental,
    )

    from src.workflow.nodes.fundamental_analysis.graph import (
        get_fundamental_analysis_subgraph,
    )

    fa_graph = await get_fundamental_analysis_subgraph()
    result = await fa_graph.ainvoke(subgraph_input.model_dump())

    # Extract and map model_type for parent state
    model_type = "saas"
    fundamental_ctx = result["fundamental"]
    if fundamental_ctx.analysis_output:
        raw_model = fundamental_ctx.analysis_output.get("model_type")
        model_type = map_model_to_skill(raw_model)

    return {
        "fundamental": result["fundamental"],
        "model_type": model_type,
        "node_statuses": {"fundamental_analysis": "done"},
    }


async def financial_news_wrapper_node(state: AgentState) -> dict:
    """
    Wrapper for financial news research subgraph with isolated state.

    Transforms parent AgentState → FinancialNewsSubgraphState → parent updates.
    """
    from src.workflow.nodes.financial_news_research.subgraph_state import (
        FinancialNewsSubgraphState,
    )

    subgraph_input = FinancialNewsSubgraphState(
        ticker=state.ticker,
        intent_extraction=state.intent_extraction,
        financial_news=state.financial_news,
    )

    from src.workflow.nodes.financial_news_research.graph import (
        get_financial_news_research_subgraph,
    )

    news_graph = await get_financial_news_research_subgraph()
    result = await news_graph.ainvoke(subgraph_input.model_dump())

    return {
        "financial_news": result["financial_news"],
        "messages": result.get("messages", []),
        "node_statuses": {"financial_news_research": "done"},
    }


async def intent_extraction_wrapper_node(state: AgentState) -> dict:
    """
    Wrapper for intent extraction subgraph with isolated state.

    Transforms parent AgentState → IntentExtractionSubgraphState → parent updates.
    """
    from src.workflow.nodes.intent_extraction.subgraph_state import (
        IntentExtractionSubgraphState,
    )

    subgraph_input = IntentExtractionSubgraphState(
        ticker=state.ticker,
        user_query=state.user_query,
        messages=state.messages,
        intent_extraction=state.intent_extraction,
    )

    from src.workflow.nodes.intent_extraction.graph import (
        get_intent_extraction_subgraph,
    )

    intent_graph = await get_intent_extraction_subgraph()
    result = await intent_graph.ainvoke(subgraph_input.model_dump())

    return {
        "intent_extraction": result["intent_extraction"],
        "ticker": result.get("ticker"),  # Intent extraction resolves ticker
        "messages": result.get("messages", []),
        "node_statuses": {"intent_extraction": "done"},
    }


# Helper for initialization
_compiled_graph = None
_saver = None


async def get_graph():
    """Lazy-initialize and return the compiled graph with persistent checkpointer."""
    global _compiled_graph, _saver
    if _compiled_graph is None:
        try:
            logger.info("=== [DEBUG] get_graph: Starting graph compilation ===")

            # 1. All subgraphs now use wrapper nodes with isolated state
            # (Wrappers handle subgraph initialization internally)
            logger.info("[DEBUG] get_graph: Using wrapper nodes for all subgraphs")

            # 2. Build Parent Graph
            logger.info("[DEBUG] get_graph: Building parent graph...")
            builder = StateGraph(AgentState)
            builder.add_node("intent_extraction", intent_extraction_wrapper_node)
            builder.add_node("fundamental_analysis", fundamental_analysis_wrapper_node)
            builder.add_node("financial_news_research", financial_news_wrapper_node)
            builder.add_node("consolidate_research", consolidate_research_node)
            logger.info("[DEBUG] get_graph: Adding debate_wrapper_node...")
            builder.add_node(
                "debate", debate_wrapper_node
            )  # ✅ Using wrapper with isolated state
            builder.add_node("executor", executor_node)
            builder.add_node("auditor", auditor_node)
            builder.add_node("approval", approval_node)
            builder.add_node("calculator", calculation_node)
            logger.info("[DEBUG] get_graph: All nodes added successfully")

            # 3. Define edges for parallel execution
            logger.info("[DEBUG] get_graph: Adding edges...")
            builder.add_edge(START, "intent_extraction")
            builder.add_edge("intent_extraction", "fundamental_analysis")
            builder.add_edge("intent_extraction", "financial_news_research")
            builder.add_edge("fundamental_analysis", "consolidate_research")
            builder.add_edge("financial_news_research", "consolidate_research")
            builder.add_edge("consolidate_research", "debate")
            builder.add_edge("debate", "executor")
            builder.add_edge("executor", "auditor")

            builder.add_edge("auditor", "approval")
            builder.add_edge("approval", "calculator")
            builder.add_edge("calculator", END)
            logger.info("[DEBUG] get_graph: All edges added successfully")

            # 3. Initialize Checkpointer
            logger.info("[DEBUG] get_graph: Initializing checkpointer...")
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
            logger.info("[DEBUG] get_graph: Checkpointer initialized successfully")

            # 4. Compile
            logger.info("[DEBUG] get_graph: Compiling graph...")
            _compiled_graph = builder.compile(checkpointer=_saver)
            logger.info(
                "=== [DEBUG] get_graph: Graph compilation completed successfully ==="
            )

        except Exception as e:
            logger.error(
                f"❌ [DEBUG] get_graph: ERROR during compilation - {type(e).__name__}: {str(e)}"
            )
            import traceback

            logger.error(f"[DEBUG] get_graph: Traceback:\n{traceback.format_exc()}")
            raise

    return _compiled_graph
