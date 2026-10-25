# Issue 147 acceptance evidence

Status: `VERIFIED` from the combined acceptance evidence below. The latest
low-volume provider probe completed successfully through both the primary
route and the secondary-only route after primary removal. Retry was observed
in a separate bounded probe. The latest probe itself reports retry as
`INCONCLUSIVE` because both requests succeeded on their first attempt.

## Result

The integration cutover is based on `ce87c2061681c13307d93586035645d5689a73b8`.
`PostgresNotificationHub` uses PostgreSQL `LISTEN/NOTIFY` for cross-worker live
fan-out while the durable activity table remains the replay source. The
adapter has bounded subscribers, typed notification validation, publish
failure recovery through replay, and explicit lifespan cleanup.

## Independent checks

On 2026-10-25, the integration worktree passed:

```text
Backend tests: 936 passed
LLM Provider tests: 74 passed
Search tests: 106 passed
Frontend tests: 103 passed
Ruff, frontend lint, frontend typecheck, and architecture guard: passed
```

The changed runner and provider telemetry tests also passed independently:
3 runner tests and 46 gateway adapter tests. The notification adapter tests
cover two worker instances, malformed notifications, bounded delivery, and
subscriber cleanup. Runtime tests cover atomic persistence-before-publish,
replay/live races, gaps, duplicates, slow consumers, cancellation, and
terminal events.

## Docker and behavior

The isolated Compose project is `via-refactor-integration`; staging used
`BACKEND_HOST_PORT=8500` to derive `http://127.0.0.1:8500` with
`STAGING_BASE_URL` unset. Every service with a configured health check reported
healthy after building the news and FLS inference images with
`BAKE_INFERENCE_MODELS=1`; the frontend returned HTTP 200. The worktree's
named volumes were preserved.

An authenticated run through worker 1 delivered five activity events and a
cancelled terminal event to worker 2 over SSE. After worker 2 restarted, the
PostgreSQL-backed snapshot returned cursor 5. The earlier focused integration
suite also verified persistence and replay behavior. Backend health endpoints
on ports 8500 and 8501 both returned `{"status":"ok"}`.

## Staging smoke

The latest run is recorded in
`.audit/refactor-staging-smoke-20261025-xing-model-rerun.jsonl`. It
read the provisioned secret bundle through `STAGING_SECRET_FILE`, left
`STAGING_BASE_URL` unset, and derived `http://127.0.0.1:8500` from
`BACKEND_HOST_PORT`. The run verified health, register, login, both distinct
key tests, the temporary `xingchen-agi/xing4.0-29b-a4b:free` model override,
completion start, failover injection, retry observation, primary-key restore,
and model restore. The report contains no secret values or provider response
bodies.

An earlier run is recorded in
`.audit/refactor-staging-smoke-20261025-structured-outputs-rerun.jsonl`. Its
primary path made 11 provider operations and its secondary path made 17; all 28
returned `rate_limited` after two attempts each (56 provider attempts in total).
Thus retry was
`VERIFIED`, while `completion`, `live_provider`, and `failover` are
`NOT_VERIFIED` because neither key produced a successful real completion.
That smoke restored the primary key and original selected model. Sanitized
telemetry does not preserve the upstream `provider_code` or OpenRouter
`X-RateLimit-*` headers, so it cannot distinguish OpenRouter's request caps
from a model provider's own rate limit/capacity.

A previous keys-only run called each saved-key application's
`POST /{key_id}/test` route. That route calls LiteLLM
`GET /health?model_id=...`, which sends a real model health request; gateway
logs showed two such requests returning HTTP 200. Empty `provider_calls` in the
smoke report did not mean no inference occurred. The repeatable smoke now checks
saved-key fingerprints and calls OpenRouter `GET /api/v1/key` directly with the
local staging credentials. It records the documented
`free_model_daily_requests` counter and does not send a model request. The
The latest keys-only run at 2026-10-25 02:55Z verified login and both
saved-key fingerprints; each key reported 155 of 1,000 free-model daily
requests used (845 remaining).
The primary key was `healthy`; the secondary was `available` with two recent
`rate_limited` failures and a last-used timestamp of 02:54Z. See
`.audit/refactor-staging-key-health-20261025-id-map.jsonl`.

OpenRouter documents a 20-requests-per-minute free-model cap and a daily cap of
50 or 1,000 depending on credits purchased. The daily counter is available in
`GET /api/v1/key` as `free_model_daily_requests`; the primary and secondary
queries returned the same count because both keys belong to the same OpenRouter
account, so the second key does not provide an independent daily quota. Separate
keys still allow credential-level failover, but do not isolate account-level
limits or shared model-provider capacity. The matching counters establish that
the keys share quota; they do not by themselves prove that this caused the
observed 429s.
OpenRouter also says additional accounts or keys do not increase rate limits
because capacity is governed globally, while different models have different
limits. This supports excessive workflow request volume or shared/provider
capacity as plausible causes, but does not identify which limit produced the
observed 429s. The earlier full smoke emitted 27 rate-limited records across
six minute buckets (8, 4, 3, 8, 1, and 3); 28 provider operations were each
retried once. The timing alone does not prove that one minute exceeded the
20-request cap, and provider telemetry still omits upstream limit headers.
The source is therefore inconclusive between an OpenRouter rate limit and
model-provider capacity. See the [OpenRouter limits documentation](https://openrouter.ai/docs/api_reference/limits.md).

The product's saved-key `Test` button remains a model-connection check because
the settings route receives only a key ID and LiteLLM's managed-model response
does not expose `litellm_params.api_key`. Switching that route to OpenRouter
account metadata requires a provider-owned credential access design; do not
copy raw credentials into frontend or backend state. New-key add/replace
already checks the supplied credential through OpenRouter `GET /models`,
without inference. The staging smoke uses `GET /api/v1/key` for credential
validity and free-model quota, then keeps actual model generation in a separate
low-volume gate. This is preferable for routine key checks; a model request is
still needed to prove that a particular inference route can complete.

The smoke now defaults to low-volume `provider-probe`, which calls the typed
LLM Provider Service completion contract with an eight-token response bound.
A 2026-10-25 02:44Z run returned HTTP 200 and non-empty text through the
authenticated user-scoped route before primary removal, but the result ended
with `finish_reason=length` and had no key fingerprint attribution. It is not
counted as a verified completion. Its secondary-only response had HTTP 200 and
empty text.
A 02:48Z run using the previously successful fixed model
`xingchen-agi/xing4.0-29b-a4b:free` returned HTTP 502 `rate_limited` on both the
primary path and the secondary-only path after primary deletion; each had two
attempts, so retry was observed. The 02:49Z key-health read showed the
secondary deployment had just been used and recorded `rate_limited`. Primary
and selected-model restoration passed. The secondary path was reached, but no
usable secondary completion succeeded. These probes used a daily counter of
154/1,000, so daily exhaustion is ruled out; a per-minute limit or shared model
capacity remains plausible, not proven. `.audit/refactor-staging-provider-probe-20261025.jsonl`,
`.audit/refactor-staging-provider-probe-20261025-rerun.jsonl`, and
`.audit/refactor-staging-provider-probe-20261025-xing.jsonl` contain the
sanitized reports. Set `STAGING_SMOKE_MODE=full` to run the higher-volume full
agent workflow.

After the cooldown, one direct two-token `openrouter/free` request returned
HTTP 200 at zero cost, and a direct structured-output request to
`xingchen-agi/xing4.0-29b-a4b:free` returned valid JSON at zero cost. The later
full workflow smoke with that same fixed model verified both keys, model
override, retry observation, failover injection, and cleanup, but no workflow
provider request succeeded: the primary path recorded 13 operations (26
attempts) and the secondary path 16 operations (32 attempts), all
`rate_limited`. The provider logs span multiple minute buckets, but do not
include upstream rate-limit headers; they do not establish that this run alone
exceeded the documented per-minute cap. The evidence rules out an invalid key
and shows individual model requests can succeed, but the complete workflow and
secondary-key completion remain `NOT VERIFIED`. Sanitized direct probe metadata
is recorded in `.audit/refactor-openrouter-probes-20261025.jsonl`.

At 02:56:56Z, a direct request using the secondary credential for
`xingchen-agi/xing4.0-29b-a4b:free` returned outer HTTP 200 with
`error.code=429` in the response body, no usage metadata, and no rate-limit
headers or provider identification. This places the rejection in the OpenRouter
response path, but does not distinguish a request cap from upstream model
capacity.

The 03:07Z post-cooldown probe is recorded in
`.audit/refactor-staging-provider-probe-20261025-post-cooldown.jsonl`. Login
and both non-inference key/account checks passed at 155/1,000. The primary
completion and the secondary-only completion after primary deletion both
returned HTTP 200 with empty text and `finish_reason=length`; the response
identified the secondary deployment, but provided no key fingerprint. The
completion and failover gates are `NOT_VERIFIED`, retry is `INCONCLUSIVE`,
and primary restoration passed. This low-volume run followed an 11-minute
cooldown, so the result does not support daily quota exhaustion or an invalid
credential; rate limiting or model-provider response quality remains unresolved.

The initial probe revision raised the output bound from eight to 64 tokens and
added managed `deployment_id` matching as a fallback when LiteLLM omits its
key-fingerprint header. The historical 03:07Z run remains `NOT_VERIFIED`; the
later bounded probes below evaluate those changes.

The prior smoke cleanup originally reported `primary_restore=NOT_VERIFIED`
because it required another inference-based key test. The smoke now verifies
restoration using the saved key fingerprint, and a no-inference recovery run
plus the latest smoke both verified primary-key restoration and model restore.

At 03:20Z, the 64-token provider probe using the known
`xingchen-agi/xing4.0-29b-a4b:free` model returned HTTP 200 on both the initial
and secondary-only paths. The deployment IDs matched the saved secondary key
where selected, but both outputs ended with `finish_reason=length` at the
64-token limit (249 and 243 characters). The sanitized report is
`.audit/refactor-staging-provider-probe-20261025-64tokens.jsonl`.

The smoke's default single-word probe bound is now 256 output tokens. At
03:25Z, this provider probe returned one natural completion with HTTP 200, five
characters of text, and `finish_reason=stop`; its deployment ID matched the
saved secondary key ID. After deleting the primary deployment, the
secondary-only completion returned HTTP 502 `rate_limited` after two attempts.
That is direct retry evidence, but the smoke version used for this run marked
the separate `retry` check `INCONCLUSIVE` because it examined only the initial
completion. The smoke now checks retry evidence from the failover request when
the initial completion had no retry. At 03:31Z, the corrected gate recorded
retry as `VERIFIED`. Primary-key and model restoration passed. The two low-volume probes used five
provider attempts over about five minutes, and this failover request was
rate-limited despite being well below OpenRouter's documented 20 free-model
requests per minute. Both keys reported 159/1,000 daily requests before this
run. The evidence rules out daily exhaustion and an over-20/minute probe burst;
it remains inconclusive between another account-level limit and shared model-
provider capacity. The report is
`.audit/refactor-staging-provider-probe-20261025-256tokens.jsonl`.

At 03:31Z, after increasing the configured backoff base to one second, the
initial completion received `rate_limited` on attempt one and completed on
attempt two. After primary deletion, the secondary-only request was
`rate_limited` on both attempts, so failover completion remains
`NOT_VERIFIED`. The corrected smoke recorded retry as `VERIFIED` from this
failover request. Both keys reported 160/1,000 daily requests before the run,
with 840 remaining. The run used four provider attempts; together with the
prior bounded probes it remained below the documented per-minute free-model
cap. This excludes daily exhaustion and our probe volume as the demonstrated
cause, but the shared-account or model-provider limit remains unresolved. See
`.audit/refactor-staging-provider-probe-20261025-backoff-1s.jsonl`.

A post-run keys-only check made no inference request and confirmed the primary
key remained healthy while the secondary recorded `failure_count=2`,
`last_error=rate_limited`, and `last_used_at=03:31:34Z`. Both keys reported the
same 161/1,000 account counter, with 839 remaining. This confirms the
secondary deployment was the one exercised and rate-limited after primary
removal; it still does not distinguish an account limit from model-provider
capacity. See `.audit/refactor-staging-keys-only-20261025-post-backoff.jsonl`.

At 03:37Z, the same low-volume probe was repeated with the different free model
`google/gemma-4-31b-it:free`, discovered from the public model catalog. The
initial completion and secondary-only completion both returned HTTP 502
`rate_limited` after two attempts. The shared daily counter remained at
161/1,000 before the run; primary-key and selected-model restoration passed.
This reduces the likelihood that the failures are specific to the earlier Xing
model, but does not distinguish an account-wide free-tier limit from shared
OpenRouter/provider capacity. See
`.audit/refactor-staging-provider-probe-20261025-google-gemma.jsonl`.

A follow-up keys-only check confirmed both credentials still shared 161/1,000
daily requests. The primary was healthy; the secondary had
`failure_count=3`, `last_error=rate_limited`, and `last_used_at=03:37:08Z`,
confirming the second deployment was exercised. See
`.audit/refactor-staging-keys-only-20261025-post-google.jsonl`.

The latest low-volume provider-probe run is
`.audit/refactor-staging-smoke-20261025-resume-followup.jsonl`. It left
`STAGING_BASE_URL` unset and derived `http://127.0.0.1:8500` from
`BACKEND_HOST_PORT`. Health, register, login, both non-inference key checks,
primary completion, primary-key removal, secondary-only completion, and
primary-key restoration all passed. The two account checks each reported
161/1,000 daily requests used. Both completions returned HTTP 200, non-empty
text, and `finish_reason=stop`; the secondary-only completion was attributed
to the saved secondary deployment after the primary deployment had been
removed. This run used two completion requests, below the documented
20-requests-per-minute cap. Its retry result was `INCONCLUSIVE` because neither
request needed a retry.

Retry has separate direct staging evidence in
`.audit/refactor-staging-provider-probe-20261025-backoff-1s.jsonl`: the first
completion attempt returned `rate_limited`, the second completed successfully,
and the report marked retry `VERIFIED`. Together, that run and the latest
provider-probe verify real completion, retry, and secondary-key failover. The
latest run's nonzero script exit reflects only its inconclusive retry check;
it does not invalidate the separately observed retry behavior.

Final integration checks on the current worktree passed: backend suite plus
the separately rerun fresh-PostgreSQL resume-claim test (940 passed, 5
skipped); LLM Provider tests (75 passed, 1 skipped); frontend tests (105
passed), typecheck, lint, and production image build; Ruff and the architecture
guard. The SQL claim test created its schema in a new PostgreSQL database,
proved concurrent resume claims have one winner, and left zero resume rows.
The rebuilt Compose backend, provider service, frontend, PostgreSQL, Redis,
gateway, search service, and both inference services were healthy; backend
`/health` returned `{"status":"ok"}`, the resume route appeared in OpenAPI,
and frontend returned HTTP 200. The existing cross-worker live delivery,
cancel, restart, and cursor-recovery evidence remains recorded above.

## Verdict

`VERIFIED`. The current diff, focused and full service tests, fresh PostgreSQL
resume claim, rebuilt Compose health, OpenAPI route, live completion, retry,
secondary-only failover, and key restoration have all been independently
checked. The two OpenRouter keys belong to one account and share its daily
counter and account-level limits; `GET /api/v1/key` does not report remaining
per-minute capacity. The previous 429s therefore cannot be attributed solely
to the 20-per-minute cap, but the low-volume rerun now proves that both the
primary and secondary routes can complete successfully. #147 may be merged and
closed; close epic #143 after the child issue is closed.
