# LiteLLM OpenRouter POC

This is the single-instance gateway experiment for issue #92. It routes the
project's `openrouter-default` alias to OpenRouter's OpenAI-compatible API and
registers a default credential and an explicit fallback credential so key
selection and cooldown behavior can be observed without changing agent code.

Run it from the repository root:

```bash
export LITELLM_MASTER_KEY='replace-with-a-local-gateway-key'
export OPENROUTER_API_KEY_1='replace-with-the-first-openrouter-key'
export OPENROUTER_API_KEY_2='replace-with-the-second-openrouter-key'
export LLM_GATEWAY_BASE_URL='http://llm-gateway:4000'
docker compose --profile llm-gateway up -d postgres llm-gateway
curl -fsS http://localhost:4000/health/liveliness
./scripts/litellm_poc_smoke.sh
```

The gateway uses a dedicated `litellm` database on the existing Postgres
service. The one-shot `llm-gateway-db-init` service creates that database so
LiteLLM's Prisma migration history cannot collide with LangGraph's tables. It
is intentionally a single instance and does not claim distributed Redis
coordination. The project backend should later call the internal URL with
`LLM_GATEWAY_API_KEY`; the browser must never call this port or receive an
OpenRouter key.

The model alias is `openrouter-default` and currently targets OpenRouter's
`auto` route. `openrouter-fallback` is used after a configured default-route
failure. LiteLLM's `allowed_fails`, `cooldown_time`, and explicit fallback map
provide the simplified MVP policy. The two configured slots are request-time
failover; they do not create, rotate, or revoke OpenRouter credentials.

The application adapter owns only its bounded gateway retry policy. It honors a
gateway `Retry-After` header and caps the delay. Configure that policy with
`LLM_GATEWAY_MAX_ATTEMPTS`, `LLM_GATEWAY_BACKOFF_SECONDS`,
`LLM_GATEWAY_MAX_BACKOFF_SECONDS`, and `LLM_GATEWAY_JITTER_SECONDS`.

A real staging run must verify model IDs, `HTTP-Referer`, `X-Title`, usage,
401/429/5xx mapping, and streaming behavior with disposable OpenRouter
credentials. Larger key pools, distributed coordination, and Vault remain
outside this MVP and require a follow-up issue if operational evidence shows
the two-slot route is insufficient.
