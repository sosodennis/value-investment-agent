# Frontend Error Handling Integration Report

## 1. Current Situation Analysis

Based on the review of `frontend/src/hooks/useAgentReducer.ts`, `frontend/src/components/agent-outputs/GenericAgentOutput.tsx`, and `frontend/src/types/agents/index.ts`, the frontend is **partially compatible** with the proposed backend error handling capabilities, but requires updates to fully visualize them.

### ✅ Compatible Mechanisms
- **State Ingestion**: `useAgentReducer` correctly receives `state.update` events and merges them into the agent's `output`. If the backend sends `error_logs`, it will be present in `agents[id].output.error_logs`.
- **Status Updates**: The reducer blindly accepts status strings from `node_statuses`. If the backend sends "degraded", the frontend state will reflect it (though it might violate TypeScript strict types initially).

### ⚠️ Gaps & Risks
- **Invisible Errors**: `GenericAgentOutput.tsx` only renders `preview` or `artifact`. It does not check for or render `error_logs`. Users will not know if non-fatal errors occurred (e.g., "Retrying connection...").
- **Missing Status UI**: The `AgentStatus` type does not include `degraded`. If an agent enters this state, the UI might default to a "Processing" spinner or a generic fallback, failing to convey that the agent is working at reduced capacity.
- **Type Safety**: `frontend/src/types/agents/index.ts` restricts `AgentStatus` to `'idle' | 'running' | 'done' | 'attention' | 'error'`. Sending "degraded" will cause type mismatch warnings during development or potentially fallback UI issues.

## 2. Integration Plan

To align the frontend with the "Enterprise LangGraph" backend standards, we propose the following changes:

### Phase 1: Type System Updates
1.  **Update AgentStatus**: Modify `frontend/src/types/agents/index.ts`:
    ```typescript
    export type AgentStatus = 'idle' | 'running' | 'done' | 'attention' | 'error' | 'degraded';
    ```

    **Status Semantics:**
    *   **`error` (Critical Failure)**: The agent crashed or failed completely. No usable result/artifact was produced. The UI should block the view and show the error.
        *   *Example*: API Key missing, Database unreachable, GraphRecursionError (without recovery).
    *   **`degraded` (Partial Failure)**: The agent finished and produced a result (Artifact), but some sub-tasks failed. `error_logs` will contain details. The UI should show the result **WITH** a warning indicator.
        *   *Example*: One of 3 news sources timed out (but others worked), FinBERT failed (analysis missing but article present).
    *   **`attention`**: Waiting for user input (unchanged).

2.  **Add ErrorLog Interface**: Define the structure for error logs in the frontend types.
    ```typescript
    export interface AgentErrorLog {
        node: string;
        error: string;
        timestamp: string;
        severity: 'warning' | 'error';
    }
    ```

### Phase 2: Component Updates
1.  **GenericAgentOutput Enhancement**:
    -   Modify `GenericAgentOutput.tsx` to check for `(output as any).error_logs`.
    -   Render an "Error Log" accordion or "Warning" alert box if logs exist, even if the status is "done".
2.  **Status Badge Updates**:
    -   Update `AgentCard.tsx` (and `GenericAgentOutput` header) to handle `degraded` status, perhaps using a yellow/orange "warning" icon distinct from the red "error" icon.

### Phase 3: Retry Feedback
1.  **Stream Handling**: The backend `RetryPolicy` might emit "retry" events. We should ensure these don't flicker the UI. The current `useAgentReducer` handles explicit `agent.status` events well, but we simply need to ensure the backend emits `status: "running"` during retries to keep the UI active.

## 3. Implementation Priority
This frontend work can be done **in parallel** with the backend refactoring, or **immediately after** the Core Agents backend work is verifiable.

### Estimated Effort
-   **Complexity**: Low
-   **Files to Modify**: `types/agents/index.ts`, `components/agent-outputs/GenericAgentOutput.tsx`

## 4. Verification Plan
1.  **Manual Test**: Mock the `useAgent` hook to inject a state with `status: 'degraded'` and `output: { error_logs: [...] }`. Verify the UI displays the warning badge and error list.
