# Financial News Agent Error Handling Estimation Report

## 1. Current Situation Analysis

Based on the review of `finance-agent-core/src/workflow/nodes/financial_news_research/` against the LangGraph Best Practices (Enterprise Whitepaper), the current implementation status is as follows:

### ✅ Strengths (Compliant)
- **State Architecture**: Uses **Three-Layer State Architecture** (`FinancialNewsInput`, `FinancialNewsState` as TypedDict, `FinancialNewsOutput`).
- **Control Flow**: Uses `Command(goto=...)` for explicit routing.
- **Artifact Management**: deeply integrated with `ArtifactManager`. Passes IDs (`search_artifact_id`, `news_items_artifact_id`) instead of raw data.
- **Async & Concurrency**: correctly uses `asyncio.gather` for parallel fetching and `asyncio.to_thread` for CPU-bound FinBERT analysis.

### ⚠️ Gaps & Risks (Non-Compliant)
- **Missing Retry Policies**: `search_node` (DuckDuckGo search) and `fetch_node` (HTTP scraping) are highly prone to transient network errors (timeouts, rate limits) but lack `RetryPolicy`.
- **Ad-Hoc Error Logging**: Error states are tracked via `internal_progress: {"searching": "error"}`, which is opaque. There is no `error_logs` accumulator.
- **Silent Failures**: `fetch_node` catches exceptions during async fetch and falls back to `None` ("Falling back to empty contents"). While this prevents crashing, it might lead to "silent failures" where the agent generates a report based on 0 articles without clearly warning the supervisor.
- **View Logic Coupling**: `search_node` constructs view-specific dictionaries (`top_headlines` list in `preview`).

## 2. Refactoring Plan

### Phase 1: State & Schema Enhancement
1.  **Add Error Logs**: Update `FinancialNewsState` in `subgraph_state.py` to include `error_logs`.

### Phase 2: Resilience Implementation
1.  **Add RetryPolicy**:
    -   In `build_financial_news_subgraph`, attach `RetryPolicy` to `search_node` and `fetch_node`.
    -   Configuration: `max_attempts=3`, `initial_interval=0.5`, `backoff_factor=2.0`, `jitter=True`.
    -   Configure retries to handle `ClientError`, `TimeoutError`, and `RateLimitError`.
2.  **Safety Wrappers**:
    -   `selector_node`: Wrap the LLM selection logic to handle JSON parsing failures specifically (already partially done, but can be standardized).
    -   `analyst_node`: Ensure `finbert_analyzer` failures don't crash the entire node (already has try-except, but should log to `error_logs`).
3.  **Circuit Breaker**: If `search_node` returns 0 results after retries:
    -   Use `Command(update={"status": "no_data"}, goto="end_node")` to short-circuit the flow.
    -   This prevents the "silent failure" anti-pattern and avoids wasting LLM tokens in `selector_node`.

### Phase 3: Code Clean-up
1.  **Extract Mappers**: Move `preview` construction logic to `mappers.py`.

### Estimated Effort
-   **Complexity**: Medium
-   **Files to Modify**: `subgraph_state.py`, `graph.py`

## 3. Verification Plan
1.  **Unit Test**: Mock `news_search_multi_timeframe` to throw `TimeoutError` and verify `RetryPolicy`.
2.  **Manual Verification**: Run with a ticker that produces no news (e.g., a fake ticker) to verify the "Circuit Breaker" / early exit logic.
