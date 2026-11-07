# Issue 347 acceptance evidence

Status: implementation checkpoint complete; issue remains open pending PR review
and merge to `main`. This issue is the owning-layer blocker for #325.

## Exact source

- Issue: #347, `codex/issue-347-valuation-time`
- Base: `origin/main` at `83fb733d9b23d51712ba30c41818e46e1fafa24b`
- Exact implementation commit: `e72b2bd9231f1279a72109ffd0aadb4931d78bf8`
- Earlier issue-scoped checkpoints retained on the branch: `897602c2`,
  `8a3fe1af`, `abb8a1ee`, and `f9152308`.
- No reset, squash, force update, or overwrite was used.

## Acceptance checks

| Check | Command or observation | Result |
| --- | --- | --- |
| Agent request contract | `uv run pytest tests/agents/fundamental -q` from `finance-agent-core/` | exit 0; 42 passed |
| Fundamental service suite | `uv run pytest -q` from `fundamental-service/` | exit 0; 245 passed, 25 skipped, 1 warning |
| Agent lint/format | `uv run ruff check src/agents/fundamental tests/agents/fundamental` and `uv run ruff format --check src/agents/fundamental tests/agents/fundamental` | exit 0 |
| Architecture boundary | `python3 scripts/architecture_guard.py` | exit 0; no boundary violations |
| Python compile | `python3 -m compileall -q finance-agent-core/src/agents/fundamental fundamental-service/src/fundamental_service` | exit 0 |
| Diff hygiene | `git diff --check` | exit 0 |
| Compose configuration | issue-347 project with operations + SEC-ingestion verification files and pinned runtime hashes | exit 0 |
| Docker build | Fundamental service image built from the exact branch | exit 0; image `sha256:93b8677b7d558a4d7047f3d42c927da9d4aa6d43400b8c87a05ad765196d7f27` |
| Docker health | project `value-investment-agent-issue-347-valuation-time`; PostgreSQL port 18698 and service port 18697 | both containers healthy; `docker compose ... ps` exit 0 |
| Service readiness | `curl -fsS http://127.0.0.1:18697/readyz` | exit 0; `{"status":"ready","contract_version":"internal.v1"}` |
| Naive timestamp API gate | signed `POST /v1/data/snapshots/resolve` with `2026-01-01T00:00:00` | HTTP 400 `invalid_request`; no service operation ran |
| Aware timestamp API gate | same signed request with `2026-01-01T00:00:00Z` | HTTP 422 `DATA_RELEASE_PROFILE_REQUIRED`; timestamp passed parsing and reached the application boundary |

The repository pre-commit hook also passed Ruff and Ruff-format on each code
checkpoint. A direct service-directory `uv run ruff` invocation was not
available because that project does not install a `ruff` executable; the
repository hook and Agent project runner supplied the available lint checks.

## Behavior covered

- The Agent creates one timezone-aware effective timestamp at request
  acceptance, preserves caller `requested_as_of`, rejects naive/conflicting
  timestamps, and materializes versioned `latest_complete/count=3` or unique
  explicit fiscal periods.
- Agent-to-service snapshot selection carries the effective timestamp and
  selector. Service cache keys include both the valuation timestamp and a
  digest of the fiscal selector.
- Fundamental snapshots, ingestion responses, snapshot resolution, facts,
  valuation context, calculation trace, and calculation artifacts reject
  timezone-naive valuation timestamps.
- Fiscal resolution uses issuer period end metadata, filters facts by
  availability at the caller timestamp, returns the resolved period metadata,
  and reports a missing fiscal-year gap as `degraded` instead of silently
  substituting another period.

## Not run / remaining limits

- No production deployment, external load test, or long-duration soak was
  run for this contract change.
- The Docker probe used an empty issue-scoped PostgreSQL volume, so the live
  aware request intentionally stopped at `DATA_RELEASE_PROFILE_REQUIRED`;
  seeded release activation and a successful live MSFT three-period snapshot
  are still part of #325's service-backed workspace acceptance.
- The #347 branch has no PR or merge SHA yet. Do not close #347 or mark #325
  verified until the PR is reviewed, merged to `main`, and #325 is rerun from
  that exact merge commit.
