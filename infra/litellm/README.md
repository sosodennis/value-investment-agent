# LiteLLM OpenRouter POC

This is the single-instance gateway experiment for issue #92. The project
provider contract sends the logical `openrouter-default` route; the authenticated
backend resolves it to an opaque per-user LiteLLM alias before the request
reaches OpenRouter. The project settings API adds database-backed LiteLLM
deployments after testing a key, so the gateway database is the only source of
OpenRouter credentials.

The Compose service is pinned to a reviewed image digest. Update the digest
only after validating a new LiteLLM release against the POC smoke and contract
tests.

Run it from the repository root:

```bash
export LITELLM_MASTER_KEY='replace-with-a-local-gateway-key'
export LLM_GATEWAY_BASE_URL='http://llm-gateway:4000'
docker compose --profile llm-gateway up -d postgres llm-gateway-db-init llm-gateway
curl -fsS http://localhost:4000/health/liveliness
./scripts/litellm_poc_smoke.sh
```

The gateway uses a dedicated `litellm` database on the existing Postgres
service. The one-shot `llm-gateway-db-init` service creates that database so
LiteLLM's Prisma migration history cannot collide with LangGraph's tables. It
is intentionally a single instance and does not claim distributed Redis
coordination. `mem_limit`, `cpus`, the pinned image digest, the healthcheck, and
the loopback-only host binding make this a bounded local POC. Set those limits
through `LLM_GATEWAY_MEMORY_LIMIT` and `LLM_GATEWAY_CPUS` when the host needs a
different budget.

The project backend calls the internal URL with `LLM_GATEWAY_API_KEY`; the
browser must never call this port or receive an OpenRouter key. The master key
is supplied through the deployment environment (or an external secret
injector), never committed to Compose or the config file.

For local development, the backend exposes the provider settings routes through
a loopback-only local-admin session. The settings page creates this session
automatically; it does not require `LLM_PROVIDER_ADMIN_TOKEN`. Set
`APP_ENV=production` to disable the local session. Keep
`CORS_ALLOWED_ORIGINS` and `LOCAL_ADMIN_ALLOWED_ORIGINS` restricted to the
actual frontend origins when using a non-default port.

The logical route is `openrouter-default`; authenticated users resolve it to
`openrouter-user-<sha256(user_id)[:20]>`. Each tested key for one user is
registered as a deployment in that user's pool, while another user resolves to
a different pool. The settings page selects a zero-cost OpenRouter model
(default: `openrouter/free`) and synchronizes it into managed deployments.
LiteLLM's `allowed_fails`, `cooldown_time`, and model-group routing provide the
simplified MVP policy. The settings page controls which deployments exist and
which free upstream model they use.

The application adapter owns only its bounded gateway retry policy. It honors a
gateway `Retry-After` header and caps the delay. Configure that policy with
`LLM_GATEWAY_MAX_ATTEMPTS`, `LLM_GATEWAY_BACKOFF_SECONDS`,
`LLM_GATEWAY_MAX_BACKOFF_SECONDS`, and `LLM_GATEWAY_JITTER_SECONDS`.
Attempts are hard-capped at three and the default policy adds up to `0.25s`
jitter to the exponential delay. Upstream response bodies are not copied into
the project error contract.

A real staging run must verify model IDs, `HTTP-Referer`, `X-Title`, usage,
401/429/5xx mapping, and streaming behavior with disposable OpenRouter
credentials. The current POC is deliberately limited to one gateway instance;
#91 and #97 own distributed cooldown, multi-worker, and rollout evidence.
Larger key pools and Vault remain outside this MVP.
