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

Provider settings are user-scoped in the current delivery. Every settings
request requires the shared `app_session` principal; the server derives the
user id from that session and never accepts an owner id or provider admin token
from the browser. A user can list, test, add, and delete only deployments
claimed by that user. The development-only loopback local-admin endpoint still
exists for local diagnostics, but it does not authorize provider settings.

The authenticated `/stream` API binds the session-derived principal to a
`ContextVar` for each workflow request. The compiled graph stays shared and
does not store a user id in agent wiring. The provider runtime requires a
principal. A missing principal returns
the non-retryable `provider_context_missing` error. The provider adapter
resolves the user's opaque gateway route for each completion or stream; browser
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

The application adapter retries provider requests. Interactive requests default
to two attempts. Background requests default to three. A global cap limits both
classes to three provider requests. LiteLLM also retries a deployment once
within each provider request. The configured upstream-dispatch limits are four
for interactive work and six for background work. The provider runtime
configuration sets the global cap and request-class budgets.

Backoff starts at `1s` and stops at `8s`. The adapter honors a numeric
`Retry-After` header and caps the delay. It reduces upstream response
bodies to stable status-based reasons before returning errors. Invalid
requests, policy rejections, schema failures, and cancellation are terminal.
Transient timeout, rate-limit, and selected upstream failures may be retried.
Streaming may fail over only before the first delta or tool side effect. After
bytes have been delivered, the adapter raises `stream_interrupted` with the
partial output instead of replaying the request.

## Migration shape

Agent application services consume `LLMProviderPort` through typed completion
and structured requests. LangGraph still owns workflow state and callbacks;
model requests no longer depend on the LangChain chat-model compatibility API.

The default runtime is `EmbeddedLiteLLMProvider`. It creates one long-lived
LiteLLM Router per provider-service process, translates the project model alias
to an opaque per-user route, and keeps router retry/cooldown state on shared
Redis. Provider-owned PostgreSQL deployments store encrypted OpenRouter keys;
the project adapter does not expose them to agents or the browser.
Multi-key user pools and key health tracking were delivered under #90;
delegated roles and secret-manager integrations remain outside the MVP.
LiteLLM cools a deployment after its first retryable failure. The setting
`allowed_fails: 0` sets this threshold, and `cooldown_time: 30` keeps the
deployment unavailable for 30 seconds. Redis shares cooldown state between
Router processes. Cross-process cooldown, real OpenRouter behavior, and broader
failure-injection evidence remain acceptance gates for #189.

The application constructs one shared provider runtime per process. Local and
canonical Compose development use the embedded runtime. The model group is
derived from the authenticated user id, while provider-owned encrypted
deployments are the source of truth for that user's configured OpenRouter keys.

The project database stores selected-model settings, ownership metadata, and
provider-owned encrypted OpenRouter keys. The encryption key is supplied as
`LLM_PROVIDER_ENCRYPTION_KEY` and must be backed up with the service database.
Existing keys that remain only in an old LiteLLM database are not silently
reset; #190 records the required explicit migration or re-key decision before
those retained records can be retired.
Vault and cloud secret-manager integrations are deferred.

Basic telemetry records request outcome, attempt/retry counts, latency,
time-to-first-token, stream interruption, and token usage in bounded counters
and structured logs. Prompts, raw provider errors, and credentials are excluded.
Counters are process-local and reset on restart; durable metrics export,
dashboards, budgets, quotas, and cost accounting are outside the MVP.

Per-key operational health is separate from aggregate request telemetry. A
pinned LiteLLM callback records only the managed deployment id, a bounded
outcome/error code, timestamps, consecutive failures, and the configured
cooldown expiry in a namespaced Redis hash. It runs after normal model dispatch
and never sends an additional prompt. The settings API first applies the
authenticated user's ownership filter, then reads health only for those key
ids. Health is best-effort and expires after 90 days; LiteLLM's Router remains
authoritative for actual deployment cooldown and selection.
