# Issue 147 acceptance evidence

Status: `INCONCLUSIVE` overall. All non-LLM integration gates passed; the live
provider/failover gate remains open because the staging secret bundle was not
available in this run.

## Result

The integration cutover is `ce87c2061681c13307d93586035645d5689a73b8`.
`PostgresNotificationHub` uses PostgreSQL `LISTEN/NOTIFY` for cross-worker live
fan-out while the durable activity table remains the replay source. The
adapter has bounded subscribers, typed notification validation, publish
failure recovery through replay, and explicit lifespan cleanup.

## Independent checks

```text
uv run pytest -q
934 passed, 5 skipped

uv run ruff check src tests
All checks passed

python -m compileall -q api src tests
python3 scripts/architecture_guard.py
Architecture guard passed with no boundary violations.

npm ci && npm run lint && npm run typecheck && npm test -- --run
18 test files passed, 103 tests passed
```

The notification adapter tests cover two worker instances, malformed
notifications, bounded delivery, and subscriber cleanup. The existing runtime
tests cover atomic persistence-before-publish, replay/live races, gaps,
duplicates, slow consumers, cancellation, and terminal events.

## Docker and behavior

The isolated project `via-refactor-integration` started with unique ports and
fresh project-scoped volumes. Backend, frontend, PostgreSQL, Redis, LLM
Provider, and Search health checks passed. The model inference services were
started with `BAKE_INFERENCE_MODELS=0`, so their readiness is intentionally
not asserted in this non-LLM gate.

An authenticated run through worker 1 returned `202`; worker 2 received 17
`workflow.activity` events and terminal events over SSE, and its snapshot
cursor was 17. After worker 2 stopped and restarted, replay returned the same
events from PostgreSQL. `scripts/refactor_staging_smoke.sh` derived
`http://127.0.0.1:8200` from `BACKEND_HOST_PORT`, recorded `health=VERIFIED`,
and safely recorded `live_provider=INCONCLUSIVE` and
`failover=INCONCLUSIVE` with `missing_secret_bundle` without printing or
requesting credentials.

## Verdict

`INCONCLUSIVE`. The shared delivery implementation and all local integration
behavior are verified. Do not close #147 or claim the final cutover until the
human-provisioned staging account and disposable OpenRouter key allow the
script to prove login, key test, real completion, retry, and failover.
