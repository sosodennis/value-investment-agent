from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .nodes import auditor_node, calculation_node, executor_node
from .nodes.planner.graph import get_planner_subgraph
from .state import AgentState


def approval_node(state: AgentState) -> Command:
    """
    Waits for human approval using the interrupt() function.
    """
    print("--- Approval: Requesting human approval ---")

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

    # When resumed, ans will contain the payload sent from frontend (e.g. { "approved": true })
    from langchain_core.messages import AIMessage, HumanMessage

    # Persist interaction to history
    new_messages = [
        AIMessage(
            content="",
            additional_kwargs={
                "type": "approval_request",
                "data": interrupt_payload.model_dump(),
            },
        ),
        HumanMessage(content="Approved" if ans.get("approved") else "Rejected"),
    ]

    if ans.get("approved"):
        print("✅ Received human approval.")
        return Command(
            update={"approved": True, "messages": new_messages}, goto="calculator"
        )
    else:
        print("❌ Final approval rejected.")
        return Command(update={"approved": False, "messages": new_messages}, goto=END)


# Helper for initialization
_compiled_graph = None
_saver = None


async def get_graph():
    """Lazy-initialize and return the compiled graph with persistent checkpointer."""
    global _compiled_graph, _saver
    if _compiled_graph is None:
        # 1. Initialize Subgraph
        planner_graph = await get_planner_subgraph()

        # 2. Build Parent Graph
        builder = StateGraph(AgentState)
        builder.add_node("planner", planner_graph)
        builder.add_node("executor", executor_node)
        builder.add_node("auditor", auditor_node)
        builder.add_node("approval", approval_node)
        builder.add_node("calculator", calculation_node)

        builder.add_edge(START, "planner")
        builder.add_edge("planner", "executor")
        builder.add_edge("calculator", END)

        # 3. Initialize Checkpointer
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        conn = await aiosqlite.connect("checkpoints.sqlite")
        _saver = AsyncSqliteSaver(conn)

        # 4. Compile
        _compiled_graph = builder.compile(checkpointer=_saver)

    return _compiled_graph
