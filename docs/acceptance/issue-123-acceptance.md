# Issue #123 Acceptance Report

- Base SHA: `cf3d6b952689544fba057dac0e212bea37f8cc08`.
- Implementation SHA: `a88c55e1b0c5a22703727b0ab8bc16fe95c96c57`.
- Typing review follow-up SHA: `2f801db`.
- Implementation scope: Search service runtime, PostgreSQL control plane, DDGS
  and Tavily adapters, and the Search service Compose stanza.
- Verdict: PASS for contract-normalized provider execution, encrypted
  owner-scoped persistence, atomic priority/settings updates, persisted
  cooldown, bounded fallback/deadlines/concurrency, redacted telemetry, and
  isolated container startup. Live upstream credentials were not used.

## Evidence

- PASS: `cd search-service && uv run ruff check src tests scripts`.
- PASS: `cd search-service && uv run ruff format --check src tests scripts`.
- PASS: `cd search-service && uv run pytest -q` (`94 passed, 1 skipped`). The
  PostgreSQL integration test is skipped without `SEARCH_TEST_DATABASE_URL`.
- PASS: PostgreSQL integration against the isolated Compose database using
  `SEARCH_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/langgraph`
  and a disposable Fernet key (`1 passed`). It verifies simultaneous key
  inserts receive unique priorities, user isolation, ciphertext at rest,
  cooldown exclusion and expiry, and decryption through a fresh adapter.
- PASS: `cd search-service && MYPYPATH=../finance-agent-core uv run --with mypy mypy --strict --disable-error-code=valid-type src` (`8 source files`). The development dependency `asyncpg-stubs` provides checked asyncpg types; no import suppression is needed, and `_save_key` checks the optional `RETURNING` row.
- PASS: `cd search-service && uv run python -m compileall -q src scripts`.
- PASS: `python3 scripts/architecture_guard.py` and `git diff --check`.
- PASS: `LITELLM_MASTER_KEY=compose-validation-only SEARCH_SERVICE_HOST_PORT=18083 POSTGRES_HOST_PORT=15432 docker compose -p value-investment-agent-issue123-search-runtime config --quiet`.
- PASS: the same isolated Compose project built and started `search-service`
  with `SEARCH_PROVIDER_ENCRYPTION_KEY` set to a disposable Fernet key.
  `GET /livez` returned `{"status":"ok"}` and `GET /readyz` returned
  `{"status":"ready","contract_version":"internal.v1"}` after PostgreSQL
  was healthy. A first probe immediately during container recreation returned
  an empty reply; the service then reached healthy state and both probes
  succeeded.
- PASS: provider adapter mocks cover Tavily normalization and rate-limit
  mapping, DDGS capability declarations and timeout capacity retention. The
  timeout regression test blocks one thread past the request deadline and
  confirms a second request cannot start until that worker exits.
- PASS: telemetry test observes stable provider/correlation/operation/error
  fields and confirms query and key strings are absent from captured logs.

## Runtime and ownership

- DDGS and Tavily implement the SearchProvider boundary and normalize output
  into `SearchResult`. Tavily keys are sent in the HTTPS JSON body. DDGS runs
  in a fixed-size executor; cancellation retains the internal capacity permit
  until the non-cancellable worker finishes.
- Search-owned PostgreSQL tables persist encrypted keys, per-user provider
  preferences and priorities, test/status metadata, and cooldown state. Writes
  use owner-scoped transactions and a transaction advisory lock. Fernet keys
  are supplied by `SEARCH_PROVIDER_ENCRYPTION_KEY` and never stored in the DB.
- Provider execution uses at most three priority-ordered attempts per request,
  one request deadline, and a per-process semaphore. Cooldown and priority are
  shared through PostgreSQL across replicas; the outer in-flight semaphore is
  process-local and therefore bounds each replica independently.
- Telemetry records correlation ID, provider, operation, result count or stable
  error code. It omits provider keys, query text, and upstream exception text.
- No live DDGS or Tavily calls were run. Deployments must supply a stable,
  backed-up Fernet key and provider credentials where required. Search schema
  initialization is idempotent on first control-plane use.

## Changed files

- `docker-compose.yml` (Search service stanza only).
- `search-service/README.md`
- `search-service/pyproject.toml`
- `search-service/uv.lock`
- `search-service/src/search_service/app.py`
- `search-service/src/search_service/providers.py`
- `search-service/src/search_service/postgres_control_plane.py`
- `search-service/tests/test_boundary.py`
- `search-service/tests/test_providers.py`
- `search-service/tests/test_postgres_control_plane.py`

## Typing review follow-up

- Added `asyncpg-stubs` to the development dependency group because the asyncpg runtime package does not ship a `py.typed` marker.
- Removed the `import-untyped` suppression and the redundant class and test comments.
- Strict mypy passes across all eight source files. The full Search Service suite passes (`94 passed, 1 skipped`); PostgreSQL integration remains skipped when `SEARCH_TEST_DATABASE_URL` is unset.
