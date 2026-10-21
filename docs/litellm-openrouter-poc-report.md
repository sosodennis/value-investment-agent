# LiteLLM OpenRouter POC report

Date: 2026-10-22

## Scope

This POC validates the isolated LiteLLM service, its database-backed deployment
metadata, and the project adapter boundary. The production data plane now
resolves `openrouter-default` to an opaque per-user alias (see
`docs/rfc/llm-provider-contract.md`); this POC does not reintroduce a global
shared pool.

## Reproduction

```bash
export LITELLM_MASTER_KEY='local-gateway-key'
docker compose --profile llm-gateway up -d postgres llm-gateway-db-init llm-gateway
./scripts/litellm_poc_smoke.sh
```

The smoke check calls liveness and authenticated model-list endpoints. It never
prints or sends an OpenRouter key to the browser. A real upstream request is
opt-in and requires a disposable key added through the authenticated settings
API.

## Observed results

- The reviewed LiteLLM image is pinned by digest in Compose and targets the
  ARM64 development host. The service has a healthcheck, bounded CPU/memory
  settings, and a loopback-only host binding.
- LiteLLM uses a dedicated `litellm` database on the existing Postgres service;
  reusing the LangGraph database fails the Prisma migration baseline check.
- `/v1/models` requires the service master key. `/model/info` metadata is
  filtered by the project adapter and never returns upstream credentials.
- The project settings API creates database-backed deployments after probing a
  submitted OpenRouter key. Authenticated users receive their own deterministic
  pool alias; platform-admin compatibility remains separate and is not used by
  the authenticated workflow data plane.
- A previous disposable-key run reached OpenRouter and returned `401 User not
  found`; an explicit two-slot fallback caused LiteLLM to attempt the second
  credential. This proves the route and authorization path, and bounded
  explicit fallback, but not fair rotation or recovery for a larger pool.
- The project adapter preserves the provider contract, bounded retry policy,
  first-byte streaming boundary, and fake adapter fallback. These behaviors are
  covered by the backend contract suite.

## Decision

**Go for the isolated MVP gateway; no-go for production multi-worker rollout.**
The pinned single-instance service and database-backed deployment metadata are
adequate for the current per-user MVP. The deployment is intentionally limited
to one gateway instance because this Compose POC does not configure LiteLLM's
distributed Redis state. #91 owns cooldown/failover policy completion and #97
owns the final multi-worker/rollout gate.

The remaining live staging evidence is explicit rather than implied: disposable
real keys must still prove successful selection across requests, 401/429
cooldown and replacement, pre-first-byte stream fallback, post-first-byte
terminal errors, and behavior after gateway/Postgres degradation. No live key
is committed or required for unit and configuration verification.
