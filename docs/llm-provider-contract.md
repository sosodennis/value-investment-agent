# LLM provider contract

The application owns the model-access contract in
`finance-agent-core/src/shared/llm/contracts.py`. LangGraph nodes and
application services consume that port; they do not know about OpenRouter API
keys, LiteLLM, HTTP clients, or provider SDK exception classes.

## MVP boundary

OpenRouter is the only upstream provider, reached through the internal LiteLLM
gateway at `https://openrouter.ai/api/v1`. LiteLLM implements the gateway and is
replaceable behind this contract. Direct OpenAI fallback is not part of the
production contract.

The first delivery is platform-admin scoped. Multi-tenant ownership and Vault
or another secret manager are deferred composition concerns; adding them later
must not change `CompletionRequest`, `CompletionResult`, or stream semantics.

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

Bounded retry and model failover belong to the adapter/gateway. The MVP gateway
defaults to two attempts (hard-capped at three), exponential backoff from
`0.25s`, an `8s` maximum, and up to `0.25s` additive jitter;
`LLM_GATEWAY_MAX_ATTEMPTS`,
`LLM_GATEWAY_BACKOFF_SECONDS`, `LLM_GATEWAY_MAX_BACKOFF_SECONDS`, and
`LLM_GATEWAY_JITTER_SECONDS` make those limits explicit. A numeric or HTTP-date
`Retry-After` header is honored and capped by the maximum delay. Upstream
response bodies are reduced to stable status-based reasons before they cross
the contract. Invalid
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
simplified MVP, LiteLLM owns credential selection through the explicit
`openrouter-default` -> `openrouter-fallback` route and its cooldown settings.
The project adapter does not receive, rotate, or persist OpenRouter keys. A
larger key pool, distributed coordination, and tenant-scoped ownership remain
follow-up work under #91.

The application constructs one shared gateway provider. Local development also
uses the gateway; it does not create a direct OpenRouter or OpenAI client.
