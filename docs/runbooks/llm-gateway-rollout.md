# LLM gateway rollout

This runbook applies to the internal LiteLLM gateway that fronts OpenRouter.
The project backend remains the only control-plane API for user keys and model
settings. Do not send an OpenRouter key to LiteLLM's browser UI or commit one
to an environment file tracked by Git.

## Preflight

Set a deployment-only `LITELLM_MASTER_KEY` in the shell or an ignored local
environment file. For a staging run, also prepare two disposable OpenRouter
keys and record only their labels and fingerprints. Never paste the raw values
into logs, issue comments, test fixtures, or screenshots.

Validate the rendered Compose file and start the shared dependencies:

```bash
LITELLM_MASTER_KEY="$LITELLM_MASTER_KEY" \
LLM_GATEWAY_WORKERS=2 \
docker compose --profile llm-gateway config --quiet

LITELLM_MASTER_KEY="$LITELLM_MASTER_KEY" \
LLM_GATEWAY_WORKERS=2 \
docker compose --profile llm-gateway up -d postgres redis llm-gateway-db-init llm-gateway

./scripts/litellm_poc_smoke.sh
```

The gateway must be healthy, `/health/liveliness` must respond, and the
authenticated model-management endpoints must not expose key material. Redis
must be healthy before the gateway starts; it owns shared Router cooldown and
proxy coordination state. `LLM_GATEWAY_WORKERS=1` is the local fallback when
debugging a worker-specific failure.

## Staging evidence

Through the authenticated project settings page, add the disposable keys to
one user's pool and confirm that only masked metadata is returned. Run the
following cases and save request IDs, attempt numbers, deployment IDs, and
fingerprints only:

- successful requests across both workers;
- invalid key and 401/403 handling without retry storms;
- 429 with `Retry-After`, deployment cooldown, and recovery after
  `cooldown_time` expires;
- a transient failure before the first stream byte, which may fail over;
- a failure after text or tool-call bytes, which must surface
  `stream_interrupted` without replaying the request;
- gateway restart and Redis degradation, with the resulting terminal error
  recorded and no secret in logs.

The run is not a production approval until the same pool is exercised through
two workers and the observed cooldown/recovery behavior matches the RFC.

## Rollback

For a gateway-only incident, stop the optional profile and prevent new LLM
requests from entering the route:

```bash
docker compose --profile llm-gateway stop llm-gateway
```

Restore the last known-good application and Compose commit, then restart the
backend and gateway as one change. This project has no direct-provider fallback
in production; do not point the backend at OpenRouter directly as an emergency
shortcut. If a key may have leaked, remove the deployment through the
authenticated project API and revoke the key in OpenRouter according to the
staging incident procedure. Vault/cloud secret rotation is tracked separately
in #90.

Preserve Postgres and Redis volumes during rollback. Any uncertain deployment
registration is reconciled by comparing the project-owned masked metadata with
LiteLLM `/model/info`; raw provider credentials are never recovered from logs.
