# Issue #122 Acceptance Report

- Base SHA: `134263e27f6890c73b540a5e7e682a200374b0f6`.
- Implementation SHA: `956c44b` (`fix: enforce search service boundary contract`).
- Verdict: PASS for the frozen `internal.v1` request/response envelopes,
  provider-neutral route catalog, runtime-to-OpenAPI response conformance,
  bounded control-plane failures, owner-scoped key operations, and standalone
  service image startup.

## Evidence

- PASS: `cd search-service && uv run ruff check src tests scripts`.
- PASS: `cd search-service && uv run ruff format --check src tests scripts`.
- PASS: `cd search-service && uv run pytest -q` (`88 passed`).
- PASS: `cd search-service && uv run python -m compileall -q src scripts`.
- PASS: `cd search-service && MYPYPATH=../finance-agent-core uv run --with mypy mypy --strict --disable-error-code=valid-type src` (`6 source files`).
  The excluded `valid-type` findings are three existing `Literal[INTERNAL_CONTRACT_VERSION]`
  annotations in the shared `finance-agent-core/src/shared/internal_services/contracts.py`.
- PASS: `python3 scripts/architecture_guard.py`.
- PASS: `git diff --check`.
- PASS: `LITELLM_MASTER_KEY=compose-validation-only SEARCH_SERVICE_HOST_PORT=18003 docker compose -p value-investment-agent-issue122-codex-122 config --quiet`.
- PASS: the same isolated Compose configuration lists `search-service` among services and the current profiles.
- PASS: `LITELLM_MASTER_KEY=compose-validation-only docker compose -p value-investment-agent-issue122-codex-122 build search-service`.
- PASS: container smoke test returned `{"status":"ok"}` from `GET /livez`; `GET /readyz` returned 503 while unconfigured. The container and project network were removed afterward.
- PASS: commit hooks (`trim trailing whitespace`, `fix end of files`, YAML validation, large-file check, Ruff, and Ruff format).

The focused tests cover error and success response schemas against the
committed OpenAPI artifact, generator/artifact equality, malformed-wrapper
rejection, authentication and control-plane error mapping, deadlines and
redaction, strict success envelopes and empty inputs, provider priority and
capability selection, Intent `en-US` and News
`worldwide` region mappings, `zh-Hant-TW`, rejection of invalid region values,
worldwide/news option forwarding, result limits, key test redaction and
non-persistence, failed replacement preserving the active key, owner-scoped
listing/deletion, idempotent deletion, context-derived ownership, key deletion
without key material, UTC publication timestamps, liveness/readiness behavior,
request defaults, and OpenAPI route/schema mappings.

## Ownership and limits

- #123 owns durable shared credential and settings storage, production secret
  handling, and atomic per-user updates behind `SearchControlPlane`.
- The service image has no production provider registry or durable control
  plane wired by default; deployment must inject both before readiness is
  advertised.
- #124 owns the typed Search operation client and workflow integration; #125
  owns the separate authenticated settings/BFF transport and UI.
- No live upstream provider calls were made.
