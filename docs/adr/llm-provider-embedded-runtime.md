# ADR: Provider-owned LLM runtime

Status: accepted for issue #189

`llm-provider-service` is the independently deployable LLM capability service.
LiteLLM Router is an internal runtime adapter of that service. Backend callers
depend only on `LLMProviderPort` and the versioned `internal.v1` service
contract.

The service owns authentication, principal binding, user-scoped provider
settings, encrypted provider credentials, deployment lifecycle, normalized
errors, and application retry/streaming semantics. LiteLLM owns model-provider
translation, deployment selection, and runtime cooldown within the service.

There is one runtime path. A separate LiteLLM HTTP gateway, compatibility
adapter, or provider fallback is not part of the project architecture. Existing
keys that remain only in an old LiteLLM database require the explicit migration
or re-key decision tracked by #190 before those retained records can be retired.

## Constraints

- Existing public request, response, structured-output, and stream contracts do
  not change.
- Raw provider keys are encrypted with the provider service encryption key and
  are never returned by the service or written to logs/metrics.
- Every process owns a long-lived Router instance. Deployment mutations are
  persisted first and reconciled into every replica through a database revision
  and Redis invalidation; a Router is not recreated for every request.
- The service fails closed when the encryption key, database, or required Redis
  coordination cannot be initialized.

## Verification

The implementation must pass service contract tests, two-replica lifecycle and
state reconciliation tests, retry/stream fault injection, ownership and secret
redaction checks, and Compose readiness checks. Production acceptance also
requires the retained-key decision recorded in #190.
