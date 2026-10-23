# Internal capability service contract

This package defines only stable wire primitives used when the backend calls a
separately deployed LLM, inference, or Search service. It does not define
service operations, provider choices, finance policy, HTTP clients, or service
lifecycle.

## Trust boundary

The product API authenticates the browser session first. It derives
`subject_id` from the authenticated user record (currently `Principal.user_id`)
and creates one `InternalRequestContext` per outbound call. The browser session
cookie, browser bearer credentials, CSRF token, and provider keys never leave
the product API.

The backend sends its service credential separately in
`Authorization: Bearer <service-token>`. The capability service compares that
credential with its configured expected token using
`authenticate_internal_request` before accepting any caller-provided
principal. Missing credentials, an unset service secret, a bad credential, and
malformed context all fail closed. Deployments should supply credentials from a
secret manager and restrict service traffic to a private network. This shared
secret convention authenticates the backend workload; the principal identifies
the end user inside that authenticated call.

## Request and response

Each service owns its operation schema and places its payload beside `context`:

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

`contract_version` versions these shared context primitives. It is separate
from a service's own operation schema version, such as `inference.v1`. Each
service response echoes `correlation_id` and `contract_version` beside its
service-owned result. Clients reject a mismatched correlation ID or unsupported
version.

```json
{
  "correlation_id": "1f128da9-052d-4e64-9f13-82d9b3ec7ea1",
  "contract_version": "internal.v1",
  "result": {"service_owned": "result"}
}
```

`deadline_at` is an absolute RFC 3339 timestamp with a UTC offset. The model
normalizes accepted offsets to UTC and rejects naive timestamps. A client sends
the same deadline to every downstream service and computes its local timeout
from the remaining time; it does not restart the budget on each hop. Each
service remains responsible for its operation-specific limits and cancellation
behavior.

## Error envelope

Failures use the same outer shape while each service owns its stable `code`
catalog and HTTP mapping:

```json
{
  "correlation_id": "1f128da9-052d-4e64-9f13-82d9b3ec7ea1",
  "contract_version": "internal.v1",
  "error": {
    "code": "unavailable",
    "message": "service is unavailable",
    "retryable": true,
    "retry_after_ms": 250
  }
}
```

Messages must be bounded and redacted. Do not return exception text, prompt or
article contents, user credentials, provider keys, or internal URLs. Use 401
for caller authentication failures, 400 for malformed context or
service-owned request validation failures, 504 for an expired deadline, 429
for service-owned overload, and 5xx for unavailable or internal failures.
`retry_after_ms` is optional and non-negative.

## Readiness

Each service exposes unauthenticated `GET /readyz` on its private service
network. It returns HTTP 200 and this body only after the service can accept its
documented operations:

```json
{"status": "ready", "contract_version": "internal.v1"}
```

Before then it returns HTTP 503 with `status: "not_ready"`. Services own the
readiness conditions: for example, model load and warmup belong to inference;
provider control-plane dependencies belong to the LLM service. Keep liveness
separate from readiness and do not expose credentials, provider state, or
deployment internals in either response.

## Backend call pattern

```python
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from src.auth.interface.dependencies import require_current_user
from src.shared.internal_services import InternalRequestContext, InternalPrincipal


async def call_internal_service(request, *, service_input, client: httpx.AsyncClient):
    principal = await require_current_user(request)
    context = InternalRequestContext(
        principal=InternalPrincipal(subject_id=principal.user_id),
        correlation_id=str(uuid4()),
        contract_version="internal.v1",
        deadline_at=datetime.now(timezone.utc) + timedelta(seconds=5),
    )
    return await client.post(
        "http://capability-service/v1/operation",
        headers={"Authorization": "Bearer <configured-service-token>"},
        json={"context": context.model_dump(mode="json"), "input": service_input},
    )
```

The service token is configured on the backend HTTP client separately from the
JSON body. Do not derive `subject_id` from a request body, query, or header
provided by the browser.

## Service boundary pattern

The service extracts the context, authenticates the backend first, then uses
the returned typed principal. Keep HTTP status mapping in the service's HTTP
adapter:

```python
context = authenticate_internal_request(
    request.headers.get("Authorization"),
    expected_token=settings.backend_service_token,
    raw_context=body.get("context", {}),
)
```

Map `InternalAuthenticationError` to 401 and
`InternalContextValidationError` to 400. Do not parse or trust `subject_id`
before caller authentication succeeds. Validate the service-owned `input`
against its own schema in the same boundary adapter, then pass typed data to
the service domain/application layer.

## Fake services and conformance tests

`tests/fakes/internal_capability_service.py` is a small FastAPI fake that
depends only on this package and FastAPI. Backend service-client tests can run
it in-process with `TestClient` or `httpx.ASGITransport`; they should assert
that the configured service token is sent, unauthorized requests fail before
principal use, readiness exposes no sensitive information, and request and
response correlation plus the shared contract version match. The fake's echo
payload is test scaffolding, not a production operation schema.

The shared models reject unknown fields, empty identity/correlation values,
missing versions, malformed deadlines, and negative retry delays. Each service
must add tests for its own request/response schema, business behavior, and
readiness dependencies.
