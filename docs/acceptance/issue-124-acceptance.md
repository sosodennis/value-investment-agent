# Issue #124 Acceptance Report

- Base SHA: `cf3d6b952689544fba057dac0e212bea37f8cc08` (#122 merge).
- Implementation SHA: `b383081` (`feat(search): migrate Intent and News to typed client`).
- Verdict: PASS.

## Evidence

- PASS: `cd finance-agent-core && uv lock`; removed `ddgs`, `langchain-community`, and their unused transitive packages.
- PASS: full caller inventory with `rg -n "ddgs|DuckDuckGo|langchain-community|langchain_community" --glob '!reports/**' .`; no remaining callers or dependency references.
- PASS: `cd finance-agent-core && LLM_PROVIDER_SERVICE_URL=http://localhost:8001 LLM_PROVIDER_SERVICE_TOKEN=test MODEL_INFERENCE_SERVICE_URL=http://localhost:8002 MODEL_INFERENCE_TOKEN=test uv run pytest -q` (`968 passed, 5 skipped`).
- PASS: `cd finance-agent-core && uv run pytest tests/search -q` (`10 passed` after final client lifecycle cleanup).
- PASS: `cd finance-agent-core && uv run ruff format --check src/search tests/search`.
- PASS: `cd finance-agent-core && uv run ruff check src/search src/agents/intent/application/wiring.py src/agents/intent/infrastructure/search src/agents/news/application/wiring.py src/agents/news/infrastructure/search tests/search`.
- PASS: `python3 scripts/architecture_guard.py`.
- PASS: `git diff --check` and commit hooks (whitespace, end-of-file, large-file, Ruff, and Ruff format).

The fake HTTP transport tests cover both typed operation envelopes, headers,
correlation validation, empty success, provider errors, malformed responses,
timeout mapping, and authenticated per-user principal propagation. Intent
adapter tests preserve its ticker query expansion and `en-US`, year, 7-result,
safe-search defaults while mapping empty and invalid requests to its Yahoo
fallback. News adapter tests preserve worldwide region, safe search off,
week/month mapping, per-task limits, normalized article fields, retries, and
query fallbacks.

## Ownership and limits

- News query construction, task limits, timeframes, quotas, source reliability,
  ranking, retries, fallbacks, and article fetching remain in the News slice.
- Intent candidate policy remains in the Intent slice. Its Yahoo ticker lookup
  remains the independent fallback path.
- `trafilatura` remains installed for News article fetching.
- `agent-implementation-extractor`, `agent-debug-review-playbook`, and
  `architecture-standard-enforcer` were checked under
  `architecture-skill-maintainer`; no guidance changes were needed.
- No live Search Service or upstream provider calls were made.

## Follow-up: Request-Local Principal

- Base SHA: `67788c60a430ebd3e42f68b57a05758e096233d1`.
- Implementation SHA: `9262ee6fed347dc5a29a3ea6d4fc2d597676fca9` (`fix(search): require request-local principal`).
- Verdict: PASS.

The authenticated stream boundary now sets a shared request-local principal
context from the authenticated `principal.user_id` and resets it in `finally`.
The Search client reads only this context and rejects calls when it is absent;
it no longer imports from `llm_provider` or uses `SEARCH_SERVICE_SUBJECT_ID`.
Provider authentication wiring is unchanged.

- PASS: focused Search-client and stream-boundary tests (`12 passed`), covering
  principal propagation, context reset, and rejection before transport when no
  principal exists.
- PASS: full finance-agent suite (`970 passed, 5 skipped`).
- PASS: Ruff check and format check.
- PASS: `python3 scripts/architecture_guard.py`.
- PASS: source and test search found no static Search subject or Search-to-LLM
  principal references in the relevant paths.
- PASS: implementation commit hooks.

No live Search Service or upstream provider calls were made.
