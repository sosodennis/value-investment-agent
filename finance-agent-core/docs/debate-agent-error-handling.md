# Debate Agent Error Handling Estimation Report

## 1. Current Situation Analysis

Based on the review of `finance-agent-core/src/workflow/nodes/debate/` against the LangGraph Best Practices (Enterprise Whitepaper), the current implementation status is as follows:

### ✅ Strengths (Compliant)
- **State Architecture**: Uses **Three-Layer State Architecture** (`DebateInput`, `DebateState` as TypedDict, `DebateOutput`).
- **Graph Topology**: Clearly defined Directed Acyclic Graph (DAG) with parallel and sequential execution phases.
- **Resource Management**: Implements `_compress_reports` and uses Artifact Store references to manage context window limits (Charter §3.4).
- **Execution Helpers**: Logic is decomposed into `_execute_bull_agent`, `_execute_bear_agent`, etc., enabling reuse.

### ⚠️ Gaps & Risks (Non-Compliant)
- **Error Propagation**: The helper functions (`_execute_bull_agent`) wrap logic in `try-except` but re-raise the exception (`raise e`) after logging. This causes the graph to crash immediately upon any LLM or logic failure, rather than degrading gracefully (e.g., forfeiting a round).
- **Missing Circuit Breakers**: If an agent fails in Round 1, the graph attempts to continue to Round 2, which may fail due to missing history. There is no mechanism to "short-circuit" or adjust the debate rounds dynamically upon failure.
- **Ad-Hoc Error Logging**: Uses `internal_progress` for status but lacks `error_logs` for detailed audit trails.
- **Retry Logic**: Nodes like `r1_bull_node` call LLMs without an explicit `RetryPolicy`. While `ChatOpenAI` has internal retries, a graph-level policy is preferred for observability and consistency.

## 2. Refactoring Plan

### Phase 1: State & Schema Enhancement
1.  **Add Error Logs**: Update `DebateState` to include `error_logs`.
2.  **Recursion Control**: Add `loop_count` or `round_count` to the state to explicitly track debate depth and prevent `GraphRecursionError`, as recommended in the research paper.

### Phase 2: Resilience Implementation
1.  **Sub-Agent Isolation**:
    -   Wrap `_execute_bull/bear_agent` calls in a `safe_subgraph_invocation` pattern.
    -   Ensure exceptions in these helpers return a "Degraded" status rather than crashing the parent graph.
    -   Modify `_execute_bull_agent` and peers to catch exceptions and return a "fallback" response (e.g., "Analyst is silent due to technical difficulties") instead of raising.
    -   This allows the debate to continue even if one side drops out for a round.
2.  **Add RetryPolicy**:
    -   In `build_debate_subgraph`, attach `RetryPolicy` to all agent nodes (`rX_bull`, `rX_bear`, etc.) to handle transient LLM API errors.
3.  **Verdict Safety**:
    -   `verdict_node` currently has a `try-except` that returns a `Command` with `internal_progress: error`. It should be enhanced to produce a "Mistrial" or "Inconclusive" verdict artifact so the UI can still render something useful.

### Estimated Effort
-   **Complexity**: Medium
-   **Files to Modify**: `subgraph_state.py`, `nodes.py`, `graph.py`

## 3. Verification Plan
1.  **Unit Test**: Mock `ChatOpenAI.ainvoke` to raise `RateLimitError` and verify `RetryPolicy` works.
2.  **Manual Verification**: Simulate a "crash" in `r2_bull_node` (via mock) and verify that `r2_bear_node` still runs (or the debate concludes gracefully without that round).
