# LLM Provider Reliability Boundary

The reliability boundary is inside the independently deployed
`llm-provider-service`, which owns request dispatch and the embedded LiteLLM adapter.

The current reliability ownership is:

- The provider service owns deployment selection, key-scoped cooldown, the
  total attempt budget, backoff, `Retry-After` handling, redacted errors, and
  the first-byte stream boundary.
- LiteLLM makes one dispatch for the selected deployment and cannot create
  hidden attempts.
- LangGraph nodes own business fallback only. They do not select deployments,
  keys, or retry provider calls independently.

This supersedes the earlier #91 MVP decision that delegated selection and
cooldown to LiteLLM. Only an explicit OpenRouter key limit can rotate a key.
Unknown, model, account, workspace, and upstream-provider limits do not rotate.

Each non-stream completion carries a tuple of sanitized `LLMAttempt` records.
An attempt may include a validated deployment id, a validated key fingerprint,
and a normalized error code. Terminal `LLMProviderError` values carry the same
attempt history without response bodies or provider secrets. Invalid metadata
headers are discarded at the adapter boundary.

The adapter never retries a stream after text or tool-call bytes have been
delivered. A post-first-byte failure is returned as `stream_interrupted` with
partial output/tool-call data and the attempt history. Before the first byte,
transient status and transport errors may consume the bounded retry budget.

The provider runtime stores key health in namespaced Redis hashes shared by
provider replicas. PostgreSQL remains the source for ownership and encrypted
credentials. After a cooldown timestamp expires, a deployment can receive a
request again. The service does not promise one half-open probe, so concurrent
requests may test a recovering deployment. A Redis failure makes data-plane
selection fail closed and settings reports unavailable runtime health instead
of stale PostgreSQL health.
