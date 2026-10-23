# Search Service `search.v1` Contract

This document freezes the provider-neutral boundary for the independently
deployed Search Service. The service consumes the shared `internal.v1` request
context from #119 and owns only search transport, provider capability routing,
normalized results, and user-scoped provider credentials.

## Request envelope

`POST /v1/search/web` and `POST /v1/search/news` accept:

```json
{
  "context": {
    "principal": {"subject_id": "user-123"},
    "correlation_id": "corr-123",
    "contract_version": "internal.v1",
    "deadline_at": "2026-10-23T18:30:00Z"
  },
  "input": {
    "query": "semiconductor demand",
    "limit": 10,
    "region": "US",
    "time_range": "week",
    "safe_search": true
  }
}
```

The web and news inputs are distinct strict schemas. `query` is trimmed,
non-blank, and at most 500 characters. `limit` defaults to 10 and is bounded
to 50. `region`, `time_range`, and `safe_search` are optional. The service
does not accept provider-specific engine, category, ranking, ticker, or fetch
controls. The owner is always `context.principal.subject_id`; a body user ID
does not exist and is never authoritative.

The service authenticates `Authorization: Bearer <service-token>` before it
parses or uses the principal. Authentication and context parsing are separate:
the service token identifies the trusted caller and the context identifies the
end user.

## Success and normalized results

Success is HTTP 200, including no matches (`results: []`):

```json
{
  "contract_version": "internal.v1",
  "schema_version": "search.v1",
  "correlation_id": "corr-123",
  "operation": "news",
  "results": [{
    "title": "Example",
    "canonical_url": "https://example.test/story",
    "snippet": "A bounded provider-neutral summary.",
    "provider": "provider-a",
    "source": "Example News",
    "published_at": "2026-10-23T17:00:00Z",
    "image_url": "https://example.test/story.jpg",
    "provider_metadata": {"provider-a": {"rank": 1}}
  }]
}
```

`title`, `canonical_url`, `snippet`, and `provider` are normalized fields.
Optional metadata is namespaced and primitive-valued; it cannot overwrite or
replace normalized fields. Search does not define News categories, source
reliability, ranking policy, article fetching, or Intent ticker candidates.

## Capabilities and routing

Providers declare operation capabilities (`web`, `news`) and optional-field
capabilities (`region`, `time_range`, `safe_search`). A request is eligible
only when the provider is enabled for the authenticated user, has a usable
credential when required, supports the operation, and supports every supplied
optional field. Eligible providers are attempted in the user's ordered
priority. Disabled providers, missing keys, and providers in durable cooldown
are skipped. With no eligible provider, the stable outcome is
`UNSUPPORTED_CAPABILITY`.

Provider-specific options are never required by this contract. Provider
registries, credentials, cooldowns, enablement, and priorities are ports in
the service and must be implemented with durable shared state and atomic
per-user updates by #123; process-local state is not authoritative.

## Key lifecycle

The private settings boundary provides add/test, replace, list masked metadata,
and delete operations. New or replacement key material is tested before it is
activated. A failed test is not persisted as an active credential. Raw keys
are accepted only at this secret boundary, are passed to the provider test,
and are never returned or included in normal logs/errors. Lists expose only
provider, label, suffix, fingerprint, enabled state, and priority.

## Deadlines, bounds, and errors

`deadline_at` is one absolute UTC deadline. Provider attempts and fallback use
the remaining time; the service bounds query length, result count, and total
attempts. It never resets the deadline for a retry. The finite error set is:

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `INVALID_ARGUMENT` | 400 | Invalid envelope or input |
| `UNAUTHENTICATED` | 401 | Missing or invalid service credential |
| `UNSUPPORTED_CAPABILITY` | 422 | No provider can serve operation/options |
| `RATE_LIMITED` | 429 | Provider/service rate limit |
| `DEADLINE_EXCEEDED` | 504 | Absolute deadline expired |
| `UPSTREAM_UNAVAILABLE` | 503 | Eligible providers unavailable |
| `MALFORMED_UPSTREAM_RESPONSE` | 502 | Provider response failed normalization |

Errors echo `contract_version`, `schema_version`, and `correlation_id`. Error
messages are generic and bounded. They never include raw keys, raw query
text, upstream payloads, or internal URLs.

## Independent service surface

`GET /livez`, `GET /readyz`, and `GET /contract` are exposed by the standalone
service. The image uses the existing BuildKit `internal-contracts` context only
for shared `internal_services` authentication/context primitives. It does not
import LangGraph, frontend, or finance-agent-core application modules.
