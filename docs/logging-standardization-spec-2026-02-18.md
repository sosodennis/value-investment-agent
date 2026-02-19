# Logging Standardization Spec
Date: 2026-02-18
Scope: `finance-agent-core`, `frontend`

## 1. Review Summary (Current Gaps)

1. Mixed output channels:
   - `logger`, `print`, and `console.*` were used together.
2. Inconsistent message style:
   - free-text/emoji logs and non-machine-readable text were mixed with structured signals.
3. Context chain was incomplete:
   - request/thread/run correlation was not consistently propagated.
4. Sensitive payload risk:
   - parts of user payload and full LLM prompt/response content could be logged.
5. Boundary observability existed but lacked unified event envelope:
   - `BOUNDARY_EVENT` existed, but non-boundary logs had no single standard format.

## 2. Enterprise Logging Contract (Mandatory)

Every production log must be machine-readable JSON by default.

### 2.1 Core Fields

1. `timestamp` (ISO8601 UTC)
2. `level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`)
3. `service` (`finance-agent-core` / `frontend`)
4. `environment` (`APP_ENV`)
5. `logger` (module path)
6. `message` (short event description)
7. `event` (stable event id, snake_case or UPPER_CASE for protocol events)

### 2.2 Correlation Fields

1. `request_id` (HTTP request scope)
2. `thread_id` (workflow thread scope)
3. `run_id` (execution run scope)
4. `agent_id` (agent scope when available)
5. `node` (workflow/orchestrator node scope)
6. `ticker` (business correlation key when available)

### 2.3 Structured Payload

1. Use `fields` object for parameters and measurements.
2. Do not concatenate business data in message strings.
3. Boundary incidents must include:
   - `event = "BOUNDARY_EVENT"`
   - `error_code`
   - `fields.payload.node`
   - `fields.payload.artifact_id`
   - `fields.payload.contract_kind`
   - `fields.payload.replay` (for non-`OK`)

### 2.4 Security & Privacy

1. Redact sensitive keys before output (`authorization`, `cookie`, `password`, `token`, `secret`, `api_key`, etc.).
2. Do not log full user prompt/input payload by default.
3. Do not log full LLM prompt/response by default.
4. Full LLM payload logging must be opt-in via `LOG_LLM_PAYLOADS=true`.

## 3. Runtime Controls

1. `LOG_FORMAT`:
   - `json` (default)
   - `text` (local debugging)
2. `LOG_LEVEL`:
   - default `INFO`
3. `LOG_SERVICE`:
   - service name override
4. `LOG_REDACT_KEYS`:
   - comma-separated custom redact keys
5. `LOG_LLM_PAYLOADS`:
   - opt-in full prompt/response logging
6. `NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_LOGS`:
   - frontend debug log switch in production

## 4. Implementation Baseline (Completed in this change)

1. Unified backend logging foundation:
   - `finance-agent-core/src/shared/kernel/tools/logger.py`
2. Unified boundary event emission:
   - `finance-agent-core/src/shared/kernel/tools/incident_logging.py`
3. Request and run context propagation:
   - `finance-agent-core/api/server.py`
4. High-risk payload logging hardening:
   - `finance-agent-core/src/workflow/nodes/intent_extraction/nodes.py`
   - `finance-agent-core/src/agents/debate/application/prompt_runtime.py`
5. Print-style backend logs removed from runtime paths:
   - `finance-agent-core/src/agents/news/data/clients/fetch.py`
   - `finance-agent-core/src/agents/news/data/clients/search.py`
   - `finance-agent-core/src/shared/kernel/traceable.py`
   - `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/extractor.py`
6. Frontend logging baseline:
   - `frontend/src/lib/logger.ts`
   - `frontend/src/hooks/useArtifact.ts`
   - `frontend/src/hooks/useAgent.ts`

## 5. Package/Agent Rollout Plan

### Phase A: Strategist (`intent`, `fundamental`)
1. Convert remaining free-text logs to stable event ids.
2. Ensure all external tool failures map to typed `error_code`.
3. Add context fields (`ticker`, `node`) at orchestrator entry.

### Phase B: Scout (`news`)
1. Normalize search/fetch/analyze/aggregate events into one taxonomy.
2. Emit latency and count metrics only via `fields`.
3. Ban raw URL content/body logs.

### Phase C: Council (`debate`)
1. Keep metadata-only logs by default.
2. Track round progression with deterministic event names.
3. Keep citation and grounding diagnostics structured.

### Phase D: Researcher/Compliance/Engine
1. Standardize parameter extraction/audit/calculation event ids.
2. Enforce numeric fields in `fields` for valuation outputs and sensitivity metadata.
3. Keep deterministic calculator logs free of LLM-specific fields.

### Phase E: Frontend
1. Replace remaining direct `console.*` with `clientLogger`.
2. Keep UI parse/network errors structured with `event` and context.
3. Align browser log event naming with backend workflow event ids where possible.

## 6. Acceptance Criteria

1. No `print()` in runtime source paths.
2. No raw prompt/user payload logging by default.
3. Every error log has stable `event` and structured `fields`.
4. Every boundary failure has `error_code` and replay diagnostics.
5. Request-to-run tracing is possible via `request_id + thread_id + run_id`.
