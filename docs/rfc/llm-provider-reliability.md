# LLM Provider Reliability Boundary

Issue #91 splits reliability ownership at the gateway boundary:

- LiteLLM owns deployment candidate selection, per-deployment cooldown, and
  upstream key rotation inside the authenticated user pool.
- The project adapter owns a hard retry ceiling, exponential backoff with
  jitter, `Retry-After` handling, redacted errors, and the first-byte stream
  boundary.
- LangGraph nodes own business fallback only. They do not select deployments,
  keys, or retry provider calls independently.

Each non-stream completion carries a tuple of sanitized `LLMAttempt` records.
An attempt may include a validated deployment id, a validated key fingerprint,
and a normalized error code. Terminal `LLMProviderError` values carry the same
attempt history without response bodies or provider secrets. Invalid metadata
headers are discarded at the adapter boundary.

The adapter never retries a stream after text or tool-call bytes have been
delivered. A post-first-byte failure is returned as `stream_interrupted` with
partial output/tool-call data and the attempt history. Before the first byte,
transient status and transport errors may consume the bounded retry budget.

The Compose POC delegates cooldown state to LiteLLM and configures both its
Router Redis and proxy-wide `coordination_redis` with the shared Redis service.
The latter keeps worker-shared auth/throttle and coordination state separate
from response caching. `LLM_GATEWAY_WORKERS` can run multiple LiteLLM workers in
one container; every worker uses the same Redis-backed cooldown and rate state.
LiteLLM stores each cooldown with a Redis TTL. After the TTL expires, the
deployment can receive requests again. The router does not guarantee a single
half-open probe across workers, so several requests can reach a recovering
deployment at once. A pinned-image contract test with fake upstreams proves
cross-process cooldown sharing and recovery after expiry. Staging with
disposable OpenRouter keys must still verify real provider behavior before
#91/#97 can close. No process-local round-robin state replaces LiteLLM's shared
cooldown state.
