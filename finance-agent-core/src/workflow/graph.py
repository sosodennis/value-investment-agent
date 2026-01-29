import os
import traceback
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg_pool import AsyncConnectionPool

from src.utils.logger import get_logger

from .interrupts import ApprovalDetails, HumanApprovalRequest
from .nodes import auditor_node, calculation_node, executor_node
from .nodes.consolidate_research import consolidate_research_node
from .nodes.debate.adapter import (
    input_adapter as debate_input_adapter,
)
from .nodes.debate.adapter import (
    output_adapter as debate_output_adapter,
)
from .nodes.debate.graph import build_debate_subgraph
from .nodes.financial_news_research.adapter import (
    input_adapter as news_input_adapter,
)
from .nodes.financial_news_research.adapter import (
    output_adapter as news_output_adapter,
)
from .nodes.financial_news_research.graph import build_financial_news_subgraph
from .nodes.fundamental_analysis.adapter import input_adapter as fa_input_adapter
from .nodes.fundamental_analysis.adapter import output_adapter as fa_output_adapter
from .nodes.fundamental_analysis.graph import build_fundamental_subgraph
from .nodes.intent_extraction.adapter import (
    input_adapter as intent_input_adapter,
)
from .nodes.intent_extraction.adapter import (
    output_adapter as intent_output_adapter,
)
from .nodes.intent_extraction.graph import build_intent_extraction_subgraph
from .nodes.technical_analysis.adapter import (
    input_adapter as ta_input_adapter,
)
from .nodes.technical_analysis.adapter import (
    output_adapter as ta_output_adapter,
)
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


# Node Adapter Implementations


async def prepare_debate_node(state: AgentState) -> dict:
    """Prepare input for debate subgraph."""
    logger.info("--- [Debate Agent] Preparing Debate ---")
    data = debate_input_adapter(state)
    data["node_statuses"] = {"debate": "running"}
    return data


async def process_debate_node(state: Any) -> dict:
    """Process output from debate subgraph."""
    logger.info("--- [Debate Agent] Processing Debate output ---")
    data = dict(state)
    return debate_output_adapter(data)


async def prepare_fundamental_node(state: AgentState) -> dict:
    """Prepare input for fundamental analysis subgraph."""
    logger.info("--- [FA Agent] Preparing Fundamental Analysis ---")
    data = fa_input_adapter(state)
    data["node_statuses"] = {"fundamental_analysis": "running"}
    return data


async def process_fundamental_node(state: Any) -> dict:
    """Process output from fundamental analysis subgraph."""
    logger.info("--- [FA Agent] Processing Fundamental Analysis output ---")
    data = dict(state)
    return fa_output_adapter(data)


async def prepare_news_node(state: AgentState) -> dict:
    """Prepare input for financial news research subgraph."""
    logger.info(
        f"--- [News Agent] Preparing News Research for ticker={state.get('ticker')} ---"
    )
    data = news_input_adapter(state)
    logger.info(
        "--- [News Agent] Setting node_statuses['financial_news_research'] = 'running' ---"
    )
    data["node_statuses"] = {"financial_news_research": "running"}
    return data


async def process_news_node(state: Any) -> dict:
    """Process output from financial news research subgraph."""
    logger.info("--- [News Agent] Processing News Research output ---")
    data = dict(state)
    result = news_output_adapter(data)
    logger.info(
        f"--- [News Agent] Output mapping complete. Status will be set to: {result.get('node_statuses')} ---"
    )
    return result


async def prepare_intent_node(state: AgentState) -> dict:
    """Prepare input for intent extraction subgraph."""
    logger.info("--- [Intent Agent] Preparing Intent Extraction ---")
    data = intent_input_adapter(state)
    data["node_statuses"] = {"intent_extraction": "running"}
    return data


async def process_intent_node(state: Any) -> dict:
    """Process output from intent extraction subgraph."""
    logger.info("--- [Intent Agent] Processing Intent Extraction output ---")
    data = dict(state)
    return intent_output_adapter(data)


async def prepare_technical_node(state: AgentState) -> dict:
    """Prepare input for technical analysis subgraph."""
    logger.info("--- [TA Agent] Preparing Technical Analysis ---")
    data = ta_input_adapter(state)
    data["node_statuses"] = {"technical_analysis": "running"}
    return data


async def process_technical_node(state: Any) -> dict:
    """Process output from technical analysis subgraph."""
    logger.info("--- [TA Agent] Processing Technical Analysis output ---")
    data = dict(state)
    return ta_output_adapter(data)


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

            # --- Subgraph Setup ---
            # (Now handled inside wrapper nodes for better isolation during migration)

            # --- Node Definitions ---
            builder.add_node(
                "prepare_intent",
                RunnableLambda(prepare_intent_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "intent_extraction"},
            )
            builder.add_node(
                "intent_agent",
                build_intent_extraction_subgraph(),
                metadata={"agent_id": "intent_extraction"},
            )
            builder.add_node(
                "process_intent",
                RunnableLambda(process_intent_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "intent_extraction"},
            )

            # Fundamental Analysis Agent (Native Subgraph Chain)
            builder.add_node(
                "prepare_fundamental",
                RunnableLambda(prepare_fundamental_node).with_config(
                    tags=["hide_stream"]
                ),
                metadata={"agent_id": "fundamental_analysis"},
            )
            builder.add_node(
                "fundamental_agent",
                build_fundamental_subgraph(),
                metadata={"agent_id": "fundamental_analysis"},
            )
            builder.add_node(
                "process_fundamental",
                RunnableLambda(process_fundamental_node).with_config(
                    tags=["hide_stream"]
                ),
                metadata={"agent_id": "fundamental_analysis"},
            )

            # Financial News Research Agent (Native Subgraph Chain)
            builder.add_node(
                "prepare_news",
                RunnableLambda(prepare_news_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "financial_news_research"},
            )
            builder.add_node(
                "news_agent",
                build_financial_news_subgraph(),
                metadata={"agent_id": "financial_news_research"},
            )
            builder.add_node(
                "process_news",
                RunnableLambda(process_news_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "financial_news_research"},
            )
            # Technical Analysis Agent (Native Subgraph Chain)
            builder.add_node(
                "prepare_technical",
                RunnableLambda(prepare_technical_node).with_config(
                    tags=["hide_stream"]
                ),
                metadata={"agent_id": "technical_analysis"},
            )
            builder.add_node(
                "technical_agent",
                build_technical_subgraph(),
                metadata={"agent_id": "technical_analysis"},
            )
            builder.add_node(
                "process_technical",
                RunnableLambda(process_technical_node).with_config(
                    tags=["hide_stream"]
                ),
                metadata={"agent_id": "technical_analysis"},
            )
            builder.add_node("consolidate_research", consolidate_research_node)

            # Debate Agent (Native Subgraph Chain)
            builder.add_node(
                "prepare_debate",
                RunnableLambda(prepare_debate_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "debate"},
            )
            builder.add_node(
                "debate_agent", build_debate_subgraph(), metadata={"agent_id": "debate"}
            )
            builder.add_node(
                "process_debate",
                RunnableLambda(process_debate_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "debate"},
            )

            builder.add_node(
                "executor", executor_node, metadata={"agent_id": "executor"}
            )
            builder.add_node(
                "auditor",
                RunnableLambda(auditor_node).with_config(tags=["hide_stream"]),
                metadata={"agent_id": "auditor"},
            )
            builder.add_node(
                "approval", approval_node, metadata={"agent_id": "approval"}
            )
            builder.add_node(
                "calculator", calculation_node, metadata={"agent_id": "calculator"}
            )
            logger.info("[DEBUG] get_graph: All nodes added successfully")

            # 3. Define edges for parallel execution
            logger.info("[DEBUG] get_graph: Adding edges...")
            builder.add_edge(START, "prepare_intent")
            builder.add_edge("prepare_intent", "intent_agent")
            builder.add_edge("intent_agent", "process_intent")

            # Parallel Routing
            builder.add_edge("process_intent", "prepare_fundamental")
            builder.add_edge("process_intent", "prepare_news")
            builder.add_edge("process_intent", "prepare_technical")

            builder.add_edge("prepare_fundamental", "fundamental_agent")
            builder.add_edge("fundamental_agent", "process_fundamental")

            builder.add_edge("prepare_news", "news_agent")
            builder.add_edge("news_agent", "process_news")

            builder.add_edge("prepare_technical", "technical_agent")
            builder.add_edge("technical_agent", "process_technical")

            builder.add_edge(
                ["process_fundamental", "process_news", "process_technical"],
                "consolidate_research",
            )
            builder.add_edge("consolidate_research", "prepare_debate")
            builder.add_edge("prepare_debate", "debate_agent")
            builder.add_edge("debate_agent", "process_debate")
            builder.add_edge("process_debate", "executor")
            builder.add_edge("executor", "auditor")

            builder.add_edge("auditor", "approval")
            builder.add_edge("approval", "calculator")
            builder.add_edge("calculator", END)
            logger.info("[DEBUG] get_graph: All edges added successfully")

            # 3. Initialize Checkpointer
            logger.info("[DEBUG] get_graph: Initializing checkpointer...")

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
            logger.error(f"[DEBUG] get_graph: Traceback:\n{traceback.format_exc()}")
            raise

    return _compiled_graph
