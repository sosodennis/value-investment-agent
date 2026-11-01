# LLM provider contract

The application owns the model-access contract in
`finance-agent-core/src/llm_provider/domain/contracts.py`. LangGraph nodes and
application services consume that port; they do not know about OpenRouter API
keys, LiteLLM, HTTP clients, or provider SDK exception classes.

## MVP boundary

OpenRouter is the current upstream provider, reached through the provider
service's embedded LiteLLM Router at `https://openrouter.ai/api/v1`. LiteLLM is
an internal runtime and is replaceable behind this contract. There is no
separate HTTP gateway or provider fallback. Direct OpenAI fallback is not part
of the production contract.

Provider settings are organization-scoped. Every settings request requires the
verified organization membership in the shared `app_session` principal; the
server never accepts a user or organization owner id, or a provider admin token,
from the browser. A member can use the organization-owned deployments, while
the application authorization layer decides which members may mutate them.
The development-only loopback local-admin endpoint still exists for local
diagnostics, but it does not authorize provider settings.

The authenticated `/stream` API binds the session-derived principal to a
`ContextVar` for each workflow request. The compiled graph stays shared and
does not store a user id in agent wiring. The provider runtime requires a
principal. A missing principal returns
the non-retryable `provider_context_missing` error. The provider adapter
resolves the organization's opaque gateway route for each completion or stream; browser
input never supplies a deployment id, route alias, or OpenRouter key.

The model picker remains a global free-model policy for the MVP. It is updated
only by an authenticated session and is synchronized into managed deployments
by the backend. Platform-admin roles, tenant delegation, Vault, and other
secret-manager integrations remain deferred; adding them later must not change
`CompletionRequest`, `CompletionResult`, or stream semantics.

## Request and response shape

`CompletionRequest` contains normalized messages, an ordered `ModelRoute`, a
request and operation identifier, bounded model parameters, timeout, optional
idempotency key, and string metadata. `CompletionResult` and `Usage` contain
only normalized response data. `StreamEvent` uses `started`, `delta`, and
`completed` events, with `error` reserved for a terminal provider failure.

Structured output carries a Pydantic response schema in `StructuredRequest`. The adapter
validates the response, performs one bounded correction request when the schema
fails, and returns the declared model; callers do not parse provider dictionaries.

## Error and streaming rules

Adapters map SDK and HTTP failures to `LLMProviderError` and
`LLMErrorCode`. Retryability, HTTP status, attempt number, request ID, and a
bounded partial output are available for application error mapping. Provider
keys, prompts, raw provider errors, and SDK objects never cross this boundary.

The provider service owns one request budget. Interactive requests default to
two upstream dispatches. Background requests default to three. Structured
schema correction consumes the same budget. LiteLLM makes one dispatch for the
selected deployment and cannot create hidden attempts. The budget uses a
monotonic deadline and clamps `Retry-After` to the remaining time.

Exponential backoff starts at `1s` and grows to `8s`. A numeric or HTTP-date
`Retry-After` value takes precedence and is bounded by the remaining request
deadline. It reduces upstream response bodies to stable status-based reasons
before returning errors. Invalid
requests, policy rejections, schema failures, and cancellation are terminal.
Transient timeout, rate-limit, and selected upstream failures may be retried.
Streaming may fail over only before the first delta or tool side effect. After
bytes have been delivered, the adapter raises `stream_interrupted` with the
partial output instead of replaying the request.

## Application boundary shape

Agent application services consume `LLMProviderPort` through typed completion
and structured requests. LangGraph still owns workflow state and callbacks;
model requests no longer depend on the LangChain chat-model compatibility API.

The default runtime is `EmbeddedLiteLLMProvider`. It resolves the authenticated
user's owned deployments, reads shared Redis health, and invokes LiteLLM for
one selected deployment at a time. Provider-owned PostgreSQL deployments store
encrypted OpenRouter keys; the project adapter does not expose them to agents or
the browser.
Multi-key user pools and key health tracking were delivered under #90;
delegated roles and secret-manager integrations remain outside the MVP.
The provider health writer cools a deployment only after an explicit key-scoped
failure. Redis shares the health state between provider replicas. A bare 429 or
an account, workspace, model, or upstream-provider limit never rotates keys.
Cross-process cooldown, real OpenRouter behavior, and broader failure-injection
evidence remain acceptance gates for #189.

The application constructs one shared provider runtime per process. Local and
canonical Compose development use the embedded runtime. The model group is
derived from the verified organization id, while provider-owned encrypted
deployments are the source of truth for that organization's configured OpenRouter keys.

The project database stores selected-model settings, ownership metadata, and
provider-owned encrypted OpenRouter keys. The encryption key is supplied as
`LLM_PROVIDER_ENCRYPTION_KEY` and must be backed up with the service database.
Existing keys that remain only in an old LiteLLM database are not silently
reset. The retained-data export/re-key or disposable-reset decision is recorded
in #190 and the provider secret lifecycle runbook before those records can be
retired.
Vault and cloud secret-manager integrations are deferred.

Basic telemetry records request outcome, attempt/retry counts, latency,
time-to-first-token, stream interruption, and token usage in bounded counters
and structured logs. Prompts, raw provider errors, and credentials are excluded.
Counters are process-local and reset on restart; durable metrics export,
dashboards, budgets, quotas, and cost accounting are outside the MVP.

Per-key operational health is separate from aggregate request telemetry. The
provider runtime records only the managed deployment id, a bounded outcome or
error code, timestamps, consecutive failures, and the configured cooldown
expiry in a namespaced Redis hash. It never sends an additional prompt. The
settings API first applies the verified organization's ownership filter, then
reads health only for those key ids. Health expires after 90 days. Redis is the
runtime health source; PostgreSQL lifecycle fields do not override an
unavailable Redis view.
