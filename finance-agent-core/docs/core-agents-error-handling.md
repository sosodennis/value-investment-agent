# Core Agents Error Handling Estimation Report

## 1. Current Situation Analysis

Based on the review of `executor/node.py`, `auditor/node.py`, and `calculator/node.py` against the LangGraph Best Practices, the current implementation status is as follows:

### ✅ Strengths (Compliant)
- **TypedDict State**: All nodes access `AgentState` which is correctly defined as a `TypedDict`.
- **Command Primitive**: All nodes use `Command` for control flow and status updates (`node_statuses: {"executor": "done"}`).
- **Preview/Artifact**: Properly integrated with `AgentOutputArtifact` for UI feedback.

### ⚠️ Gaps & Risks (Non-Compliant)
- **Generic Error Handling**: All nodes use a generic `try-except Exception` block that:
    1.  Logs the error effectively.
    2.  Returns a `Command` with `goto=END` and `node_statuses: "error"`.
    -   *Risk*: This "fail-fast" approach is safe but brittle. It provides no context on *why* it failed (e.g., missing key vs. invalid type) in a machine-readable way for the Supervisor to potentially remediate.
- **Coupled Logging**: `print()` statements are used in `calculator/node.py` instead of the standardized `logger`.
- **Missing Validation Layer**: `auditor_node` manually rehydrates Pydantic models `schema(**params_dict)` inside the node. If this fails, it crashes to the generic handler. A dedicated validation step or safer parsing would be better.
- **No Error Accumulation**: Errors are sent as `AIMessage` to the conversation stream (`messages` list) rather than a structured `error_logs` state field. This pollutes the chat history with system errors.

## 2. Refactoring Plan

### Phase 1: State & Schema Enhancement
1.  **Add Error Logs**: Ensure `AgentState` in `state.py` has the `error_logs` field (it already uses `add_messages` for `messages`, but we need a dedicated error channel).
    ```python
    error_logs: Annotated[list[dict], add_messages]
    ```

### Phase 2: Resilience Implementation
1.  **Standardize Logging**: Replace `print()` in `calculator/node.py` with `logger`.
2.  **Structured Error Reporting**:
    -   Instead of appending `AIMessage` with error text, append a structured error dict to `error_logs`.
    -   Only send a user-friendly `AIMessage` (e.g., "I encountered an issue calculating valuation...") if the error is critical and stops the workflow.
3.  **Specific Exception Handling**:
    -   Catch `ValidationError` (Pydantic) explicitly in `auditor` and `executor` to return a "Validation Failed" status rather than a generic system error.

### Estimated Effort
-   **Complexity**: Low
-   **Files to Modify**: `executor/node.py`, `auditor/node.py`, `calculator/node.py`, `state.py`

## 3. Verification Plan
1.  **Unit Test**: Inject malformed data into `executor_node` input and verify it logs to `error_logs` without crashing or sending a raw traceback to the user chat.
2.  **Manual Verification**: Run a calculation with missing parameters and check the logs.
