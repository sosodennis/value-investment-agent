# Search Service `search.v1` Contract

The independently deployed Search Service consumes the shared `internal.v1`
context from #119. It owns provider-neutral search, provider capability
routing, normalized results, and user-scoped provider credentials.

## Request and response envelopes

Every POST operation accepts exactly `context` and `input`. The principal is
the owner for settings and key operations; callers cannot supply a separate
user identifier. This example shows the News mapping.

```json
{
  "context": {
    "principal": {"subject_id": "user-123"},
    "correlation_id": "corr-123",
    "contract_version": "internal.v1",
    "deadline_at": "2026-10-23T18:30:00Z"
  },
  "input": {
    "query": "semiconductor headlines",
    "result_limit": 8,
    "region": "worldwide",
    "time_range": "week",
    "safe_search": false
  }
}
```

Search success is HTTP 200, including no matches:

```json
{
  "correlation_id": "corr-123",
  "contract_version": "internal.v1",
  "result": {
    "operation": "web",
    "results": [{
      "title": "Example",
      "canonical_url": "https://example.test/story",
      "snippet": "A bounded provider-neutral summary.",
      "provider": "provider-a",
      "provider_metadata": {"provider-a": {"rank": 1}}
    }]
  }
}
```

Errors use #119 `InternalErrorResponse`: `correlation_id`,
`contract_version: "internal.v1"`, and an `error` containing `code`, `message`,
`retryable`, and optional `retry_after_ms`.

## Search inputs and defaults

Web and news use distinct strict input schemas. Queries are trimmed, must not
be blank, and are limited to 1-512 characters. `result_limit` is 1-50; web
defaults to 10 and news to 20. `timeout_seconds` defaults to 30 and is bounded
to 1-60. `safe_search` defaults to true. `region` and `time_range` are
optional and must be either a BCP-47 locale tag or the provider-neutral
`worldwide` sentinel. Examples include `en-US`, `zh-Hant-TW`, and
`worldwide`. Supported time ranges are `day`, `week`, `month`, and `year`.

The caller-facing mappings preserve each source's region semantics. An
Intent-style lookup uses `region: "en-US"` (the BCP-47 form of the DDGS
`us-en` setting), `time_range: "year"`, `result_limit: 7`, and
`safe_search: true`. News lookups use `region: "worldwide"` and
`safe_search: false`, with `week` or `month` windows and caller-selected limits
such as 4, 8, or 10.
The service does not accept provider-specific engine, category, ranking,
ticker, or article-fetch controls.

The service authenticates `Authorization: Bearer <service-token>` before
parsing or using the principal. Authentication failures preserve
`internal_auth_unconfigured`, `internal_auth_missing`, and
`internal_auth_invalid`, each with HTTP 401.

## Operations

| Route | Input | Result |
| --- | --- | --- |
| `POST /v1/search/web` | Web search input | Normalized web results |
| `POST /v1/search/news` | News search input | Normalized news results |
| `POST /v1/providers/catalog` | `{}` | Provider operation and option capabilities |
| `POST /v1/settings/read` | `{}` | Authenticated user's provider settings |
| `POST /v1/settings/update` | Full provider preference list | Atomically replaced settings through the control-plane port |
| `POST /v1/provider-keys/test` | Provider and key | Validity only; never persisted |
| `POST /v1/provider-keys/add` | Provider, key, label | Test then activate |
| `POST /v1/provider-keys/replace` | Owned key ID, provider, key, label | Test then replace; failed tests preserve the current key |
| `POST /v1/provider-keys/delete` | Owned key ID only | Idempotent deletion; no key material is accepted |
| `POST /v1/provider-keys/list` | `{}` | Masked key metadata |

Raw keys are accepted only by key test/add/replace and are never returned in
responses. Key lists expose provider, label, suffix, fingerprint, enabled
state, and priority. Provider metadata is nested by provider name and contains
only primitive values.

## Routing, deadlines, and errors

A provider is eligible when enabled for the authenticated user, credentialed
when required, capable of the operation, and capable of every requested
option. Providers are attempted in priority order, up to three attempts.
Provider attempts and fallback share the lesser of `deadline_at` and the
request timeout. No retry resets either deadline.

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `INVALID_REQUEST` | 400 | Invalid envelope or input |
| `UNSUPPORTED_CAPABILITY` | 422 | No configured provider serves the operation/options |
| `INVALID_PROVIDER_KEY` | 422 | Key test rejected the submitted key |
| `RATE_LIMITED` | 429 | Provider/service rate limit |
| `UPSTREAM_MALFORMED` | 502 | Provider response failed normalization |
| `UPSTREAM_UNAVAILABLE` | 503 | Eligible providers are unavailable |
| `DEADLINE_EXCEEDED` | 504 | Effective request deadline expired |

Error messages are bounded and redacted; they do not include keys, query text,
upstream payloads, or internal URLs. Provider credentials, cooldowns,
enablement, priorities, and atomic per-user settings persistence are
control-plane responsibilities owned by #123.

## Executable contract

`contracts/search-service-openapi.json` is generated by:

```bash
python3 search-service/scripts/generate_openapi.py
```

The service also exposes `GET /livez`, `GET /readyz`, and `GET /contract`.
