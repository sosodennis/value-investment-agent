# LLM provider contract

The application owns the model-access contract in
`finance-agent-core/src/llm_provider/domain/contracts.py`. LangGraph nodes and
application services consume that port; they do not know about OpenRouter API
keys, LiteLLM, HTTP clients, or provider SDK exception classes.

## MVP boundary

OpenRouter is the only upstream provider, reached through the internal LiteLLM
gateway at `https://openrouter.ai/api/v1`. LiteLLM implements the gateway and is
replaceable behind this contract. Direct OpenAI fallback is not part of the
production contract.

Provider settings are user-scoped in the current delivery. Every settings
request requires the shared `app_session` principal; the server derives the
user id from that session and never accepts an owner id or provider admin token
from the browser. A user can list, test, add, and delete only deployments
claimed by that user. The development-only loopback local-admin endpoint still
exists for local diagnostics, but it does not authorize provider settings.

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
validates the response and returns the declared model; callers do not parse
provider dictionaries.

## Error and streaming rules

Adapters map SDK and HTTP failures to `LLMProviderError` and
`LLMErrorCode`. Retryability, HTTP status, attempt number, request ID, and a
bounded partial output are available for application error mapping. Provider
keys, prompts, raw provider errors, and SDK objects never cross this boundary.

The application adapter retries gateway requests. Interactive requests default
to two attempts. Background requests default to three. A global cap limits both
classes to three gateway requests. LiteLLM also retries a deployment once
within each gateway request. The configured upstream-dispatch limits are four
for interactive work and six for background work. `LLM_GATEWAY_MAX_ATTEMPTS`
sets the global cap. `LLM_GATEWAY_MAX_ATTEMPTS_INTERACTIVE` and
`LLM_GATEWAY_MAX_ATTEMPTS_BACKGROUND` set each class budget.

Backoff starts at `1s`, stops at `8s`, and adds up to `0.25s` of jitter. Set
`LLM_GATEWAY_BACKOFF_SECONDS`, `LLM_GATEWAY_MAX_BACKOFF_SECONDS`, and
`LLM_GATEWAY_JITTER_SECONDS` to change it. The adapter honors a numeric or
HTTP-date `Retry-After` header and caps the delay. It reduces upstream response
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

The current HTTP adapter is `LiteLLMGatewayProvider`. It sends the project
model alias to the gateway's `/v1/chat/completions` endpoint, translates
OpenAI-compatible usage and tool-call data, sends Pydantic JSON Schema for
structured requests, and adds request/idempotency headers. Its retry budget is
bounded and its terminal errors are non-retryable after exhaustion. For the
simplified MVP, LiteLLM owns credential selection among database-backed
deployments registered under an opaque per-user route alias; router retry and
cooldown settings apply to that user's model group. A separate fallback alias
is not part of the MVP, and staging must still verify selection and recovery
behavior. The project adapter does not receive, rotate, or persist OpenRouter
keys. A larger key pool and delegated roles remain follow-up work under #90.
LiteLLM cools a deployment after its first retryable failure. The setting
`allowed_fails: 0` sets this threshold, and `cooldown_time: 30` keeps the
deployment unavailable for 30 seconds. Redis shares cooldown state between
Router processes. The pinned-image contract test verifies cross-process
cooldown and recovery against fake upstreams. Full proxy HTTP requests, backend
concurrency, real OpenRouter behavior, and broader failure-injection evidence
remain open under #91 and #97.

The application constructs one shared gateway provider. Local development also
uses the gateway. It does not create a direct OpenRouter or OpenAI client.
The gateway model group is derived from the authenticated user id; its database
deployments are the source of truth for that user's configured OpenRouter keys.

The project database stores selected-model settings and key ownership metadata,
not raw OpenRouter keys. The project backend sends submitted key material only
to LiteLLM's internal model-management API. The pinned LiteLLM release encrypts
stored credential values with its master key when `LITELLM_SALT_KEY` is unset;
keep that master key stable while gateway deployments exist. Vault and cloud
secret-manager integrations are deferred.

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
