# Technical Analysis Agent Error Handling Estimation Report

## 1. Current Situation Analysis

Based on the review of `finance-agent-core/src/workflow/nodes/technical_analysis/` against the LangGraph Best Practices (Enterprise Whitepaper), the current implementation status is as follows:

### ✅ Strengths (Compliant)
- **State Architecture**: Correctly implements the **Three-Layer State Architecture** (`Input`, `State`, `Output`).
- **TypedDict Usage**: Internal `TechnicalAnalysisState` uses `TypedDict` with appropriate reducers.
- **Control Flow**: Uses `Command(goto=...)` for explicit transitions.
- **Artifact Management**: Stores heavy data (price series, FracDiff charts) in `ArtifactManager` and passes references, avoiding state bloat.

### ⚠️ Gaps & Risks (Non-Compliant)
- **Missing Retry Policies**: `data_fetch_node` calls `fetch_daily_ohlcv` (network IO) and `fetch_risk_free_series` without `RetryPolicy`.
- **Ad-Hoc Error Logging**: Error tracking relies on `internal_progress: {"node": "error"}`. There is no accumulative `error_logs` field.
- **Unprotected Complex Logic**: `fracdiff_compute_node` and `semantic_translate_node` contain complex mathematical operations (FracDiff, Backtesting) that could raise `ValueError`, `ZeroDivisionError`, or `PandasError`. Currently, these are only partially wrapped or rely on `Command` returns for known error states, but unexpected exceptions could crash the graph.
- **View/Analysis Coupling**: `data_fetch_node` constructs view-specific "preview" dictionaries (e.g., `latest_price_display`) inside the node. This should be delegated to a presenter/mapper.

## 2. Refactoring Plan

### Phase 1: State & Schema Enhancement
1.  **Add Error Logs**: Update `TechnicalAnalysisState` in `subgraph_state.py` to include:
    ```python
    error_logs: Annotated[list[dict], add_messages]
    ```

### Phase 2: Resilience Implementation
1.  **Add RetryPolicy**: In `build_technical_subgraph` (graph.py), attach `RetryPolicy` to `data_fetch_node`.
    -   Configuration: `max_attempts=3`, `initial_interval=0.5`, `backoff_factor=2.0`, `jitter=True`.
2.  **Safety Wrappers**:
    -   Wrap `fracdiff_compute_node` using the **Command Pattern** for graceful degradation: catch mathematical errors and return `Command(update={"status": "degraded"}, goto="next_node")` instead of crashing.
    -   Wrap `semantic_translate_node` to ensure LLM generation failures don't halt the pipeline (use fallback heuristics if LLM fails).

### Phase 3: Code Clean-up
1.  **Extract Presenters**: Move preview formatting logic (`f"${val:,.2f}"`) out of nodes into `mappers.py`.

### Estimated Effort
-   **Complexity**: Medium (due to mathematical stability requirements)
-   **Files to Modify**: `subgraph_state.py`, `graph.py`

## 3. Verification Plan
1.  **Unit Test**: Mock `fetch_daily_ohlcv` to simulate network jitter and verify retry.
2.  **Unit Test**: Inject "NaN" or infinite data into `fracdiff_compute_node` to test the safety wrapper's ability to catch math errors and log them.
3.  **Manual Verification**: Run with a ticker having sparse data to verify graceful degradation logic.
