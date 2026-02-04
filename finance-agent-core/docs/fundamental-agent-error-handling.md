# Fundamental Analysis Agent Error Handling Estimation Report

## 1. Current Situation Analysis

Based on the review of `finance-agent-core/src/workflow/nodes/fundamental_analysis/` against the LangGraph Best Practices (Enterprise Whitepaper), the current implementation status is as follows:

### ✅ Strengths (Compliant)
- **State Architecture**: Correctly implements the **Three-Layer State Architecture** (`Input` as BaseModel, `State` as TypedDict, `Output` as BaseModel).
- **TypedDict Usage**: Internal state uses `TypedDict` with appropriate reducers (`merge_dict`, `last_value`).
- **Control Flow**: Uses `Command(goto=...)` for dynamic routing instead of conditional edges, aligning with `Command` primitive best practices.
- **Artifact Management**: Implements "Reference & Store" pattern for large reports (L3 data), saving to `ArtifactManager` and passing references.

### ⚠️ Gaps & Risks (Non-Compliant)
- **Missing Retry Policies**: `financial_health_node` performs external network calls (`fetch_financial_data`) without an explicit `RetryPolicy`. Transient network errors will cause the node to fail immediately.
- **Ad-Hoc Error Logging**: Error states are tracked via `internal_progress` dictionary (e.g., `{"financial_health": "error"}`). It lacks a standardized `error_logs: Annotated[List[dict], operator.add]` field for accumulating audit trails across parallel execution or retries.
- **Coupled View Logic**: The `financial_health_node` contains ~100 lines of string formatting logic (`fmt_currency`, `wrap_text`). This increases the risk of `ValueError` or `TypeError` crashing the flow during simple data formatting. View logic should be isolated.
- **Lack of "Safe Wrapper"**: While the subgraph itself is isolated, there is no explicit wrapper ensuring that unhandled exceptions (like `KeyError` or unexpected API changes) capture the stack trace and return a "Degraded" status gracefully to the parent supervisor.

## 2. Refactoring Plan

To bring the Fundamental Analysis agent to full compliance, we propose the following changes:

### Phase 1: State & Schema Enhancement
1.  **Add Error Logs**: Update `FundamentalAnalysisState` in `subgraph_state.py` to include:
    ```python
    error_logs: Annotated[list[dict], add_messages] # or operator.add
    ```
2.  **Standardize Status**: Ensure `node_statuses` updates are consistent for both success and error paths.

### Phase 2: Resilience Implementation
1.  **Add RetryPolicy**: In `build_fundamental_subgraph` (graph.py), attach a standard `RetryPolicy` to `financial_health_node`.
    ```python
    ```python
    retry=RetryPolicy(
        max_attempts=3,
        backoff_factor=2.0,
        initial_interval=0.5,
        jitter=True,
        retry_on=(NetworkError, TimeoutError, ConnectionError)
    )
    ```
2.  **Safety Wrapper**: Wrap the node logic in a try-except block that:
    -   Catches unexpected exceptions.
    -   Appends a structured error structure to `error_logs`.
    -   Returns a `Command` routing to a graceful fallback or error end state.

### Phase 3: Code Clean-up
1.  **Extract Presenters**: Move the `fmt_currency`, `src`, and table formatting logic from `financial_health_node` to `presenters.py` or `mappers.py`. The node should only focus on orchestration (fetching -> saving -> next step).

### Estimated Effort
-   **Complexity**: Low to Medium
-   **Files to Modify**: `subgraph_state.py`, `graph.py`
-   **New Files**: `presenters.py` (optional, or move to existing `mappers.py`)

## 3. Verification Plan
1.  **Unit Test**: Mock `fetch_financial_data` to raise `NetworkError` and verify `RetryPolicy` kicks in (requires inspecting graph configuration or logs).
2.  **Manual Verification**: Run the agent with a ticker that triggers an error (e.g., invalid ticker or simulated network failure) and verify:
    -   Graph does not crash.
    -   `error_logs` contains the error details.
    -   Status is correctly reported as "error" or "degraded".
