# Frontend Findings - 06/02/2026

## [P2] Contract types are too loose at protocol boundary
- File: /Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts:5
- Summary: `Any`/`any` at the boundary makes refactors risky and breaks strict-typing requirements. Define discriminated unions for `resume_payload` and typed `AgentOutput` shapes, then generate TS types from FastAPI/OpenAPI.

## [P2] SSE parsing lacks abort/reconnect and is spec-brittle
- File: /Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgent.ts:22
- Summary: Custom parsing over fetch lacks `AbortController`, retry/backoff, heartbeat handling, and proper SSE framing (multi-line data, event ids). Use `EventSource` or a dedicated SSE parser and add reconnect with `Last-Event-ID`.

## [P2] Client-side sequencing isn’t rehydrated on history load
- File: /Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts:53
- Summary: `lastSeqId` isn’t set from server state, so replayed events can be duplicated or mis-ordered after history load. Return `last_seq_id` from `/thread` and set it in `LOAD_HISTORY` to enforce deduplication.
