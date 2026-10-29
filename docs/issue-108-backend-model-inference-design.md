# Backend model inference design

Status: Historical design record. Issues #108 and #109 are complete; use the
[current inference boundary](issue-121-inference-boundary.md) and
[rollout runbook](runbooks/model-inference-rollout.md) for current contracts and
operations.

## Problem

Issue #108 moves News sentiment and SEC forward-looking-statement (FLS)
classification behind the private service contract in
`docs/issue-106-model-inference-contract.md`. News runs in an async workflow,
while SEC extraction and its direction review are synchronous and already run
off the event loop. The backend must preserve the callers' fallbacks and FLS
cache while keeping HTTP and service schemas out of agent code.

## Usage

Composition constructs one process-scoped `ModelInference` and injects it into
News and Fundamental.

```python
async def analyze_news(text: str, inference: ModelInference) -> None:
    try:
        sentiment = await inference.news_sentiment(text)
    except InferenceFailure:
        sentiment = None
    await existing_news_analysis(text, sentiment=sentiment)
```

```python
def filter_fls(sentences: Sequence[str], inference: ModelInference) -> list[str]:
    try:
        predictions = inference.fls_predictions(sentences)
    except InferenceFailure:
        return existing_lexical_fallback(sentences)
    return existing_selection(sentences, predictions)
```

The synchronous Fundamental direction reviewer uses
`inference.news_sentiment_sync(text)` and keeps its existing metric, numeric,
confidence, and neutral-label gates. News still selects its existing basic LLM
prompt when inference has no result; it does not add an LLM skip decision.

## Shape

The public facade contains task operations and backend-owned result/error
types. `NewsSentimentResult` carries `label`, `confidence`, `scores`,
`has_numbers`, and `model_revision`; `has_numbers` remains derived from the
input text. `FLSResult` carries ordered `keep` predictions and the response's
`model_revision`. `InferenceFailure` carries a closed error code, request ID,
retryability, and an optional retry delay, without HTTP status or raw response
data.

```python
class ModelInference(Protocol):
    async def news_sentiment(self, text: str) -> NewsSentimentResult: ...
    def news_sentiment_sync(self, text: str) -> NewsSentimentResult: ...
    def fls_predictions(self, sentences: Sequence[str]) -> FLSResult: ...
```

`entrypoint.py` is the only caller-facing import. Domain operation policy owns
the input caps and 500/750 ms defaults and 1000/1500 ms maxima. The application
service creates one request ID and one monotonic deadline per logical call,
uses the remaining budget on each attempt, and allows at most two attempts.
The HTTP adapter owns both `httpx.Client` and `httpx.AsyncClient`, authentication,
wire validation, correlation headers, and conversion to `InferenceFailure`.
Both modes share request construction, response parsing, and retry eligibility.
Composition owns process-scoped client construction and shutdown.
Lazy construction is guarded by a process-local lock so simultaneous first
requests publish one service and one pair of HTTP clients. FastAPI teardown
stops request handling before it detaches the singleton under that lock and
awaits client shutdown outside the lock. The supported lifecycle does not
start inference calls while shutdown is in progress.

Retry only `MODEL_NOT_READY` and `UNAVAILABLE` when the service marks them
retryable, or `OVERLOADED` when it is retryable and includes a valid
`retry_after_ms`. Keep the same request ID and retry only when the delay and a
positive attempt budget fit inside the original deadline. Never retry
`CANCELLED`, invalid input, authentication failure, inference failure, or a
malformed response. The #106 contract permits retrying `DEADLINE_EXCEEDED` only
when inference has not started, but the current response has no reliable
started/not-started field. Therefore the backend will not retry deadline
errors until that contract can prove the request was not admitted.

News uses the async method so task cancellation closes the outstanding HTTP
request and starts neither another attempt nor fallback work. The synchronous
SEC pipeline uses the sync methods with the same bounded deadline. FLS keeps
its local sentence cache, prefilter, order restoration, and lexical fallback;
the service accepts up to 120 sentences and owns the model-call batch size of
32. The backend makes no readiness request before inference. A service failure
causes one existing workflow fallback, not another inference or LLM health
probe.

On success, validate schema version, operation, request ID, model revision,
known sentiment labels, finite confidence/scores, and exact FLS prediction
cardinality. Map bad status bodies, JSON, or result shapes to a non-retryable
backend inference failure. Tests cover sync and async HTTP success, one total
deadline, retry limits and request-ID reuse, cancellation, overload with and
without a retry delay, malformed responses, News/FLS/direction fallbacks, FLS
cache reuse, and import-hygiene boundaries. Compose configuration validation
checks endpoint and secret wiring. Backend-only rebuild behavior, runtime
artifact loading, and service failure injection are verified in issue #109.

## Synthesis decision

Candidate 1 is the base. Arena's cross-judge rated it 4/5 for public interface
depth, 5/5 for traced caller fit, 4/5 for reliability semantics, 5/5 for
behavior preservation, and 4/5 for deployment and tests. Candidate 2 scored
5/5, 4/5, 3/5, 5/5, and 5/5 respectively. Candidate 1 wins because async News
requests can propagate caller cancellation while the two synchronous SEC
paths keep their current call shape. Candidate 2's closed operation policy
registry and small task-focused facade are retained in the synthesis. A third
candidate did not complete because its model provider returned an upstream
availability error; the two completed candidates were cross-judged.

The reviewer flagged two checks for implementation: 32 is the service-side
model batch size while one backend logical request may contain up to 120
sentences, and the #107 service had to observe cancelled client requests.
Issue #109 later closed the service and cancellation verification. The design
uses a single 120-sentence FLS request where the caller cache permits it,
leaving 32-sentence model batches inside the service.

## Tradeoffs accepted

- We accept sync and async transport methods for News sentiment because News
  and Fundamental direction review have different traced execution contexts.
- We accept the sync SEC call's deadline-bounded in-flight work because the
  existing extraction pipeline is synchronous and already runs in a worker.
- We accept non-retry of deadline errors until the wire contract can prove
  inference did not start.
- We retain the backend FLS prediction cache because service request-ID
  idempotency does not replace per-sentence reuse.

## Alternatives considered

- One synchronous client with News offloaded through `asyncio.to_thread` has a
  smaller surface, but coroutine cancellation cannot promptly close the
  service request.
- One async client would require converting the synchronous SEC extraction
  path or introducing a private event-loop bridge for each synchronous call.
- Separate News and Fundamental clients would duplicate the same auth,
  correlation, response validation, deadline, and retry policy.

## Historical implementation reconciliation

This section records the original design rule for the #108 implementation. The
current service contract is maintained in the inference boundary and rollout
documentation linked above.

## Historical questions and risks

- The original design flagged `DEADLINE_EXCEEDED` admission semantics and
  cancellation propagation for #107/#109 verification. Those issues are now
  closed; the delivered behavior is covered by the service and client tests.

## Implementation status

The typed facade, shared HTTP boundary, News/FLS/direction caller migration,
and removal of backend FinBERT loading and warmup were implemented in #108 and
verified through #109. The backend still declares `torch`, `transformers`, and
`sentence-transformers` because the SEC dense retriever loads
`all-MiniLM-L6-v2` through `SentenceTransformer`. The FinBERT weights and
FinBERT inference path are no longer part of the backend image. Removing the
shared ML dependencies requires a separate dense-retriever migration or an
explicitly accepted sparse-only mode. These measurements and decisions are a
historical record; current runtime behavior is covered by the linked docs.
