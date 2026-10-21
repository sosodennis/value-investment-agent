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

The current Compose POC delegates cooldown state to LiteLLM and intentionally
runs one gateway instance. Shared Redis coordination, concurrent multi-worker
selection, half-open recovery, and real disposable-key staging evidence remain
rollout gates for #91/#97; no process-local round-robin state is introduced as
a substitute.
