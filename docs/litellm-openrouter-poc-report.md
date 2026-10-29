# LiteLLM OpenRouter POC report

Date: 2026-10-22

## Scope

This POC validates the isolated LiteLLM service, its database-backed deployment
metadata, and the project adapter boundary. The production data plane now
resolves `openrouter-default` to an opaque per-user alias (see
`docs/llm-provider-contract.md`); this POC does not reintroduce a global
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

**Go for the isolated MVP gateway.** This is the decision recorded at the time
of the POC, not a current production approval. The pinned service,
database-backed deployment metadata, and shared Redis coordination were
adequate for the per-user MVP. The Compose configuration supported multiple
LiteLLM workers through `LLM_GATEWAY_WORKERS` and configured both Router
cooldown state and proxy-wide coordination Redis. Issues #91 and #97 are
closed, while the runbook still requires disposable-key evidence before
production approval.

The POC's live staging evidence was limited to the observations above. No
credentials or live provider responses are committed as durable fixtures.
