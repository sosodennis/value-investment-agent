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
LiteLLM's Prisma migration history cannot collide with LangGraph's tables. The
Compose service defaults to one proxy worker and points Router state at the
shared Redis service. The contract test proves cooldown sharing between
independent Router processes. Full proxy HTTP requests and backend concurrency
checks remain under #91 and #97. The pinned image digest, healthcheck, resource
limits, and loopback-only host binding constrain this local POC. Set the limits
with `LLM_GATEWAY_MEMORY_LIMIT` and `LLM_GATEWAY_CPUS`.

Run the retry contract test against the pinned LiteLLM image without provider
credentials:

```bash
LITELLM_MASTER_KEY=contract-test-placeholder \
  docker compose --profile llm-gateway-contract-test up \
    --abort-on-container-exit \
    --exit-code-from llm-gateway-contract-test \
    llm-gateway-contract-test
```

The placeholder satisfies Compose interpolation. The test container does not
receive it. The test uses fake deployments and a disposable Redis service with
no host port or volume. One case sends a request through two deployments and
checks that LiteLLM dispatches once to each, cools both, and sends no upstream
traffic on the next request. Another case confirms that a second Router process
does not dispatch to a cooled deployment. The test does not exercise the full
proxy server, backend concurrency, or production load.

The project backend calls the internal URL with `LLM_GATEWAY_API_KEY`; the
browser must never call this port or receive an OpenRouter key. The master key
is supplied through the deployment environment (or an external secret
injector), never committed to Compose or the config file.

The `provider_key_telemetry` callback records the selected managed deployment
and a sanitized success/failure outcome in shared Redis after each normal
dispatch. It never logs prompt content, credentials, or raw exceptions and
does not make a model request. The backend reads namespaced health records only
for key ids owned by the authenticated user. LiteLLM's Router continues to make
deployment selection and cooldown decisions; the callback's cooldown timestamp
is display telemetry. These records expire after 90 days.

For local development, the backend still exposes a loopback-only local-admin
session for diagnostics, but provider settings require a signed-in user session
and are scoped to that user's gateway pool. Set `APP_ENV=production` to disable
the local diagnostics session. Keep
`FRONTEND_ALLOWED_ORIGINS` set to the actual frontend origins when using a
non-default port. Compose passes this one allowlist to both CORS and local-admin
origin checks.

The logical route is `openrouter-default`; authenticated users resolve it to
`openrouter-user-<sha256(user_id)[:20]>`. Each tested key for one user is
registered as a deployment in that user's pool, while another user resolves to
a different pool. The settings page selects a zero-cost OpenRouter model
(default: `openrouter/free`) and synchronizes it into managed deployments.
LiteLLM's `allowed_fails`, `cooldown_time`, and model-group routing provide the
simplified MVP policy. The settings page controls which deployments exist and
which free upstream model they use.

The application adapter retries gateway requests. LiteLLM can retry a failed
deployment once within each request. Interactive requests allow two gateway
requests. Background requests allow three. A global cap limits both classes to
three gateway requests. The maximum upstream-dispatch counts are four for
interactive requests and six for background requests.

Set `allowed_fails: 0` to cool a deployment after its first retryable failure.
Redis shares cooldown state between Router processes. The adapter honors a
gateway `Retry-After` header and caps the delay. Set
`LLM_GATEWAY_MAX_ATTEMPTS`, `LLM_GATEWAY_MAX_ATTEMPTS_INTERACTIVE`,
`LLM_GATEWAY_MAX_ATTEMPTS_BACKGROUND`, `LLM_GATEWAY_BACKOFF_SECONDS`,
`LLM_GATEWAY_MAX_BACKOFF_SECONDS`, and `LLM_GATEWAY_JITTER_SECONDS` to change
the retry policy. The default policy adds up to `0.25s` of jitter. The adapter
does not copy upstream response bodies into its error contract.

A real staging run must verify model IDs, `HTTP-Referer`, `X-Title`, usage,
401, 429, and 5xx mapping, and streaming behavior with disposable OpenRouter
credentials. The current POC is deliberately limited to one proxy worker; #91
and #97 own full proxy concurrency, broader failure injection, and rollout
evidence.
Larger key pools and Vault remain outside this MVP.

## Rollout and recovery

Deploy the backend and the pinned gateway image as one reviewed release. If a
gateway release fails its smoke or contract checks, roll the gateway image
digest back to the last reviewed digest and roll the backend back to the
matching release. The application has no in-process provider fallback; when
the gateway is unavailable, requests fail with a sanitized provider error.
Stopping the gateway disables LLM requests and key-management operations but
does not remove its database or volumes.

Deleting a managed deployment removes the application's gateway registration;
it does not revoke the original key at OpenRouter. Users manage upstream key
revocation through OpenRouter. Replacement first tests and registers the new
key, then places the old deployment into its configured grace period. If a
replacement response is lost, inspect the user's masked key list and
fingerprints before retrying; do not infer success from a client timeout.
