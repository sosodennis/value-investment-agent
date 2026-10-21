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

`src/shared/llm/contracts.py` contains provider-neutral models for:

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
| retry/cooldown and multi-worker selection | gateway reliability policy | follow-up issue #91 |
| pinned LiteLLM image and disposable OpenRouter evidence | deployment/POC | follow-up issue #92 |
| authenticated key API ownership test matrix | control/data-plane integration | follow-up issue #95 |
| frontend workflow acceptance | browser UX | follow-up issue #96 |
| full rollout gates | end-to-end verification | follow-up issue #97 |

## Deliberate limits

LiteLLM does not currently return a stable selected deployment id or key
fingerprint in the OpenAI-compatible response used by this adapter. The
contract exposes both fields so #91 can attach them when the pool selector and
cooldown registry become authoritative. Until then, attribution is optional
and no secret is reconstructed from gateway responses.
