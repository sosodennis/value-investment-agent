# Issue #136 Acceptance Report

- Base SHA: `e5561efb4dbdf9cbba78eced93ef9553f8533a5b` (`origin/main` after
  #123, #124, and #125 merges).
- Result SHA: `c81432e`.
- Verdict: PASS for the multi-key Search contract, durable key/provider health,
  bounded same-provider rotation, cross-provider fallback, ownership isolation,
  masked settings operations, and redacted service boundaries.

## Delivered behavior

- A user may own multiple keys for one provider. Search stores encrypted key
  material and enforces a unique `(owner_id, provider, fingerprint)` index.
- Key summaries expose only IDs and masked metadata, including status,
  failure count, cooldown, last tested, and last used timestamps.
- Key selection uses PostgreSQL row locks and leases so concurrent requests and
  replicas do not claim the same eligible key. Key cooldown and manual
  enablement are separate states.
- Invalid and key-scoped rate-limit failures quarantine or cool down one key;
  provider-scoped upstream and malformed failures open provider health state and
  move to the next enabled provider. One absolute deadline and a maximum of
  three attempts apply across the whole request.
- Empty results are successful. Invalid input, cancellation, and expired
  deadlines do not start new attempts. Logs and response envelopes contain no
  raw key or query text.
- Search settings now render a masked list per provider and support add/test,
  replace, delete, and enable/disable through the authenticated BFF.

## Evidence

- PASS: `cd search-service && SEARCH_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15436/langgraph SEARCH_TEST_ENCRYPTION_KEY=(disposable Fernet key) uv run pytest -q` (`107 passed`). This includes real PostgreSQL inserts for multiple keys per provider, owner isolation, encrypted storage, concurrent leases, key cooldown expiry, and persistence through a fresh control-plane instance.
- PASS: `cd search-service && uv run ruff check src tests`.
- PASS: `cd search-service && MYPYPATH=../finance-agent-core uv run --with mypy mypy --strict --disable-error-code=valid-type src` (`8 source files`).
- PASS: `cd finance-agent-core && uv run pytest -q tests/test_search_settings_api.py` (`4 passed`), including authenticated enable/disable forwarding and service-token isolation.
- PASS: `cd frontend && npm test -- --run src/app/settings/search/page.test.tsx src/lib/search-settings-api.test.ts` (`7 passed`).
- PASS: `cd frontend && npm run typecheck` and `npm run lint`.
- PASS: the generated `contracts/search-service-openapi.json` matches the
  generator and includes the multi-key settings schema and set-enabled route.
- PASS: `LITELLM_MASTER_KEY=compose-validation-only docker compose -p value-investment-agent-issue136 config --quiet`.
- PASS: isolated PostgreSQL container `value-investment-agent-issue136-postgres-1`
  reached a healthy state on host port `15436`.

## Boundaries and remaining work

- The browser calls only the finance API/BFF. Search Service receives a signed
  internal principal envelope and owns provider credentials and health state.
- #126 remains open for its separate multi-replica routing, rollback/version
  skew, and cross-service lifecycle matrix. This issue supplies the key-pool
  concurrency evidence required by that matrix but does not claim deployment
  routing evidence.
- No live upstream provider credential was stored or used in this acceptance.
