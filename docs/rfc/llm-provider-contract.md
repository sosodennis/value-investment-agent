# LLM Provider Contract

This document records the provider boundary delivered by issue #89. The
application owns authentication and workflow composition. The provider slice
owns route resolution, provider-neutral outcomes, and the LiteLLM adapter.

## Request flow

```text
verified session
    -> API task context (user_id)
    -> LangGraph singleton
    -> agent CompletionRequest (logical route: openrouter-default)
    -> provider boundary resolves opaque user pool alias
    -> LiteLLM/OpenRouter
```

The browser and LangGraph nodes never submit a LiteLLM deployment id, a model
alias for another user, or an OpenRouter key. The request-local principal is a
`ContextVar` set only by the authenticated `/stream` API boundary. The graph
can therefore remain a compiled singleton without storing user state in agent
wiring.

For a user id `U`, the gateway alias is the deterministic opaque value
`openrouter-user-<sha256(U)[:20]>`. The settings API uses the same server-side
function when registering a key, so multiple keys for one user form one
LiteLLM pool and different users resolve to different pools.

## Contract

`finance-agent-core/src/llm_provider/domain/contracts.py` contains
provider-neutral models for:

- logical routes and authenticated provider principals;
- resolved gateway routes (adapter-internal);
- completion results, stream events, and sanitized provider errors;
- optional non-secret attribution (`deployment_id`, `key_fingerprint`).

The adapter resolves a route before every completion or stream. Production
configuration enables `LLM_GATEWAY_REQUIRE_PRINCIPAL` by default. Missing
identity is a non-retryable `provider_context_missing` error. Retry and stream
first-byte semantics remain unchanged; attribution is carried through all
outcomes without prompt, cookie, token, or key material.

## Migration map

| Call site | Current boundary | Contract status |
| --- | --- | --- |
| Intent, news, debate, technical wiring | shared `LLMProviderPort` and logical `ModelRoute` | migrated; no infrastructure imports in agent nodes |
| `/stream` task creation | authenticated session ownership | migrated; principal is bound before LangGraph execution |
| LiteLLM gateway adapter | OpenAI-compatible HTTP client | migrated; user-scoped route resolution and attribution fields |
| key settings API | LiteLLM management client | migrated; authenticated users register into their opaque pool alias |
| retry/cooldown and multi-worker selection | gateway reliability policy | bounded adapter retries and Redis-backed LiteLLM cooldown are covered by deterministic contract tests; disposable-provider staging remains in #97 |
| pinned LiteLLM image and Compose topology | deployment/POC | image and Redis contract are pinned and verified by #91's deterministic gates |
| authenticated key API ownership | control-plane integration | per-user import, test, replace, delete, and ownership checks are implemented in #90 |
| frontend workflow | browser UX | key and model settings workflow is implemented in #96 |
| full rollout gates | end-to-end verification | disposable OpenRouter staging evidence remains in #97 |

## Deliberate limits

LiteLLM does not currently return a stable selected deployment id or key
fingerprint in the OpenAI-compatible response used by this adapter. The
project does not infer per-key state from that response. The pinned gateway's
custom callback reads the selected deployment id from LiteLLM's internal call
metadata and writes a sanitized outcome to a dedicated Redis key. The settings
API reads these records only after filtering deployments by authenticated user
ownership. Request content, provider credentials, and raw upstream errors are
not sent to the callback store. This records ordinary application traffic; it
does not issue extra model probes.
