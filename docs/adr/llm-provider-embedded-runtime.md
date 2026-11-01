# ADR: Provider-owned LLM runtime

Status: accepted for issue #189

`llm-provider-service` is the independently deployable LLM capability service.
LiteLLM Router is an internal runtime adapter of that service. Backend callers
depend only on `LLMProviderPort` and the versioned `internal.v1` service
contract.

The service owns authentication, principal binding, organization-scoped provider
settings, encrypted provider credentials, deployment lifecycle, normalized
errors, deployment selection, shared key health, and retry/streaming semantics.
LiteLLM remains an internal adapter for model-provider translation and one
upstream dispatch at a time.

There is one runtime path. A separate LiteLLM HTTP gateway, compatibility
adapter, or provider fallback is not part of the project architecture. Existing
keys that remain only in an old LiteLLM database require the explicit
export/re-key or retained-data decision tracked by #190 before those retained
records can be retired.

## Constraints

- Existing public request, response, structured-output, and stream contracts do
  not change.
- Raw provider keys are encrypted with the provider service encryption key and
  are never returned by the service or written to logs/metrics.
- Each request selects one eligible deployment from the verified organization's
  PostgreSQL-owned pool and creates a Router configured with zero retries and
  no fallbacks for that dispatch. The service's `AttemptBudget` covers every
  deployment dispatch, structured correction, delay, and the original request
  deadline.
- Key health is written and read from namespaced Redis hashes shared by
  provider replicas. Only explicit key-scoped failures create cooldown or
  invalid-key state. Model, account, workspace, and upstream-provider limits
  stay on the same key. Retryable model and upstream-provider limits honor
  `Retry-After` within the request deadline; account and workspace credit
  limits remain terminal.
- The service fails closed when the encryption key, database, or required Redis
  coordination cannot be initialized.

## Verification

The implementation must pass service contract tests, two-replica lifecycle and
state reconciliation tests, retry/stream fault injection, ownership and secret
redaction checks, and Compose readiness checks. Production acceptance also
requires the retained-key decision recorded in #190.
