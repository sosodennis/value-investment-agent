# LiteLLM OpenRouter POC report

Date: 2026-10-21

## Scope

This POC checks whether a single LiteLLM container can expose the project's
`openrouter-default` alias and persist tested OpenRouter deployments in
LiteLLM's database behind an internal admin key. It does not claim that key
rotation, streaming failover, or production image pinning are complete.

## Reproduction

```bash
export LITELLM_MASTER_KEY='local-gateway-key'
docker compose --profile llm-gateway up -d postgres llm-gateway-db-init llm-gateway
./scripts/litellm_poc_smoke.sh
```

The smoke check only calls the gateway liveness endpoint. It never prints or
sends a key to the browser.

## Observed results

- `docker.litellm.ai/berriai/litellm:main-stable` started on the ARM64 Docker
  host and served `/health/liveliness` with HTTP 200.
- `/v1/models` required the LiteLLM master key. The project settings API adds
  the `openrouter-default` model group after a successful OpenRouter probe.
- Reusing the LangGraph `langgraph` database failed LiteLLM's Prisma migration
  baseline check. A dedicated `litellm` database on the same Postgres service
  completed migrations successfully.
- A request with a syntactically valid disposable OpenRouter key reached
  `https://openrouter.ai/api/v1` and returned OpenRouter's `401 User not found`.
  This proves the OpenRouter route and authorization header path are active.
- Database-backed deployments in one `openrouter-default` model group are the
  planned key pool. Their selection and cooldown behavior still need a staging
  run with disposable credentials.
- The authenticated model metadata response masked the provider credentials;
  no upstream key was returned by `/model/info`.
- OpenRouter's public `/api/v1/models` catalogue exposes the `openrouter/free`
  router and explicitly `:free` concrete models. The settings API filters this
  catalogue and synchronizes the selected model into managed deployments;
  models that only report zero text-token pricing but charge for another
  modality are excluded.
- The project adapter now honors a gateway `Retry-After` value and applies a
  bounded exponential retry policy. Compose exposes the policy limits so the
  backend and contract use the same settings.

## Decision

**Go for an isolated POC and adapter contract work. No-go for production
cutover yet.** The database-backed key pool is suitable for the simplified
MVP, with LiteLLM owning key selection and cooldown. A staging run
with disposable real OpenRouter keys must still prove: key selection across
successful requests, 401/429 cooldown and replacement behavior, bounded retry,
pre-first-byte stream fallback, post-first-byte terminal errors, and behavior
after gateway/Postgres degradation. The gateway image must also move from a
mutable tag to a reviewed version or digest.

The project-owned provider contract remains the compatibility boundary. If
LiteLLM cannot provide the required key and streaming semantics, #91 can own a
small project adapter or the gateway implementation can be replaced without
changing agent/domain code.
