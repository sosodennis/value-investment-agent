# Issue 119 shared internal-service contract sketch

## Problem

The backend already has authenticated browser sessions, a typed LLM provider facade, and an inference HTTP client, but their internal identity, correlation, version, deadline, error, and readiness conventions differ. Search remains owned by individual agent adapters. Shared code must provide stable wire primitives without taking over any service's payload schema, runtime, provider SDK, or finance policy.

## Usage

The backend authenticates the browser session at the product API, derives the principal from the authenticated user, creates a request context, and sends it together with service-specific payload:

```json
{
  "context": {
    "principal": {"subject_id": "user-123"},
    "correlation_id": "1f128da9-052d-4e64-9f13-82d9b3ec7ea1",
    "contract_version": "internal.v1",
    "deadline_at": "2026-10-23T18:30:00Z"
  },
  "input": {"service_owned": "payload"}
}
```

The backend sends its service credential separately as `Authorization: Bearer <service-token>`. A capability service compares that credential to its own configured expected token before parsing or trusting `context.principal`. Browser cookies, browser bearer credentials, and provider keys are never forwarded.

Service-specific API schemas stay with their service. Responses echo `correlation_id` and `contract_version`; failures use a stable outer error envelope while retaining service-owned error codes. `/readyz` returns readiness and the supported shared contract version, with HTTP 200 when ready and 503 when not ready.

## Shape and ownership

Add `src/shared/internal_services/contracts.py` for frozen Pydantic v2 wire models that reject unknown fields: `InternalPrincipal(subject_id)`, `InternalRequestContext(principal, correlation_id, contract_version, deadline_at)`, `InternalError(code, message, retryable, retry_after_ms)`, `InternalErrorResponse(correlation_id, contract_version, error)`, and `InternalReadiness(status, contract_version)`. The module contains only stable primitives and validation; it knows no service names, operation names, finance rules, HTTP client, provider, or runtime.

Add `src/shared/internal_services/auth.py` for `authenticate_internal_request(authorization, expected_token, raw_context) -> InternalRequestContext`. It rejects missing/unconfigured credentials and mismatches with a small `InternalAuthenticationError`; compare secrets with `hmac.compare_digest`, then parse the context. This single entry point makes the required ordering explicit. HTTP adapters at each service boundary map authentication errors to 401 and Pydantic validation failures to 400. Internal code receives typed context and does not repeat validation.

The context's contract version is `internal.v1`, distinct from each service's own request schema version. `deadline_at` is an absolute UTC timestamp so independently clocked processes can enforce the same deadline; transport clients derive their local timeout from remaining time and do not extend it. Services retain operation-specific bounds and runtime behavior.

## Alternatives considered

1. Put context in common HTTP headers and leave request bodies untouched. This keeps body schemas isolated, but each client and service must separately parse headers, which weakens fake-service contract coverage and makes version/deadline validation less visible.
2. Create shared per-service request/response models or a common SDK. This reduces repetitive client code but couples service payload evolution and provider/runtime choices to a shared package, beyond the requested stable primitives.

The nested context envelope is the smallest common surface that lets clients and fake services validate identity, correlation, version, and deadline consistently while service-specific `input` remains owned by each API.

## Synthesis decision

The chosen shape is the nested context envelope. The architect arena could not dispatch candidate runners because the agent thread limit was reached, so there was no cross-model candidate or judge result. The direct comparison retained the smaller shared context shape and rejected per-service shared DTOs because the latter would couple service payload ownership to the backend package.

## Implementation reconciliation

No accepted deviations yet.

## Open risks

- Bearer credentials are a deploy-time shared-secret convention, not mutual TLS or workload identity. Deployments must keep services on trusted private networks and rotate secrets through their secret manager.
- The contract requires a single configured service credential per caller/service pair for this scope; multi-caller audiences or key rotation overlap can be added by each service deployment without changing the principal envelope.

## Next step

For #120 and #121, integrate the shared models and authenticate-before-parse helper at each service HTTP boundary, then prove malformed contexts and missing, invalid, or unconfigured credentials are rejected without importing backend implementation modules.
