# LLM provider contract

The application owns the model-access contract in
`finance-agent-core/src/shared/llm/contracts.py`. LangGraph nodes and
application services consume that port; they do not know about OpenRouter API
keys, LiteLLM, HTTP clients, or provider SDK exception classes.

## MVP boundary

OpenRouter is the only upstream provider for the first production path at
`https://openrouter.ai/api/v1`. LiteLLM may implement the internal gateway in a
later slice, but it is replaceable behind this contract. Direct OpenAI fallback
is legacy behavior and is not part of the production contract.

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

Bounded retry and model failover belong to the adapter/gateway. Invalid
requests, policy rejections, schema failures, and cancellation are terminal.
Transient timeout, rate-limit, and selected upstream failures may be retried.
Streaming may fail over only before the first delta or tool side effect. After
bytes have been delivered, the adapter raises `stream_interrupted` with the
partial output instead of replaying the request.

## Migration shape

The current LangChain-based agents will first receive a LangChain compatibility
adapter over `LLMProviderPort`. This preserves prompt composition and
LangGraph callbacks while intent, technical interpretation, news, and debate
move to typed requests. Once migration is complete, `get_llm()` and duplicated
agent retry loops can be removed. A LiteLLM HTTP adapter can then be tested
against the same port without changing agent code.

The current HTTP adapter is `LiteLLMGatewayProvider`. It sends the project
model alias to the gateway's `/v1/chat/completions` endpoint, translates
OpenAI-compatible usage and tool-call data, sends Pydantic JSON Schema for
structured requests, and adds request/idempotency headers. Its retry budget is
bounded and its terminal errors are non-retryable after exhaustion. The adapter
does not implement credential selection; that remains an explicit gateway or
key-pool policy until the OpenRouter POC proves which layer owns it.

During migration, `get_llm()` constructs one shared gateway provider and wraps
it with `LangChainGatewayModelAdapter` whenever `LLM_GATEWAY_BASE_URL` is set.
This keeps existing LangChain prompt composition working while the call sites
move to typed requests. The local compatibility path is OpenRouter-only; a
missing OpenRouter key is an explicit configuration error and never falls back
to direct OpenAI.
