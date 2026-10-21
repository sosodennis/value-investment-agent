# LiteLLM OpenRouter POC

This is the single-instance gateway experiment for issue #92. It routes the
project's `openrouter-default` alias to OpenRouter's OpenAI-compatible API. The
project settings API adds database-backed LiteLLM deployments after testing a
key, so the gateway database is the only source of OpenRouter credentials.

Run it from the repository root:

```bash
export LITELLM_MASTER_KEY='replace-with-a-local-gateway-key'
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

For local development, the backend exposes the provider settings routes through
a loopback-only local-admin session. The settings page creates this session
automatically; it does not require `LLM_PROVIDER_ADMIN_TOKEN`. Set
`APP_ENV=production` to disable the local session. Keep
`CORS_ALLOWED_ORIGINS` and `LOCAL_ADMIN_ALLOWED_ORIGINS` restricted to the
actual frontend origins when using a non-default port.

The model alias is `openrouter-default` and is the stable key-pool route. Each
tested key is registered as a database deployment in that model group. The
application settings page selects a zero-cost OpenRouter model (default:
`openrouter/free`) and synchronizes that upstream model into every managed
deployment. LiteLLM's `allowed_fails`, `cooldown_time`, and model-group routing
provide the simplified MVP policy. The settings page controls which
deployments exist and which free upstream model they use.

The application adapter owns only its bounded gateway retry policy. It honors a
gateway `Retry-After` header and caps the delay. Configure that policy with
`LLM_GATEWAY_MAX_ATTEMPTS`, `LLM_GATEWAY_BACKOFF_SECONDS`,
`LLM_GATEWAY_MAX_BACKOFF_SECONDS`, and `LLM_GATEWAY_JITTER_SECONDS`.
Attempts are hard-capped at three and the default policy adds up to `0.25s`
jitter to the exponential delay. Upstream response bodies are not copied into
the project error contract.

A real staging run must verify model IDs, `HTTP-Referer`, `X-Title`, usage,
401/429/5xx mapping, and streaming behavior with disposable OpenRouter
credentials. Larger key pools, distributed coordination, and Vault remain
outside this MVP and require a follow-up issue if operational evidence shows
the database-backed pool is insufficient.
