# Issue 198 staging acceptance

Verified implementation commit: `746c0b5` (`docs(staging): add isolated env
and deployment acceptance`). The staging stack used the dedicated
`value-investment-agent-staging` Compose project and `.env.staging` with mode
`0600`. The local staging data was disposable; its PostgreSQL and Redis volumes
were removed before the final run so the batch import started empty.

## Commands and results

All commands below ran from the repository root in the `codex/issue-198-staging-env`
worktree.

| Check | Result |
| --- | --- |
| `bash -n scripts/prepare_staging_env.sh scripts/refactor_staging_smoke.sh` | exit 0 |
| `python3 -m py_compile scripts/check_staging_secret_redaction.py` | exit 0 |
| `git diff --check` and commit hooks (ruff, ruff-format) | passed |
| `docker compose --env-file .env.staging -p value-investment-agent-staging config --quiet` | exit 0 |
| `docker compose --env-file .env.staging -p value-investment-agent-staging up -d --build` | exit 0 |
| `bash scripts/refactor_staging_smoke.sh` with the real CSV and `STAGING_REQUIRE_LIVE_PROVIDER=1` | exit 0 |
| staging log/report secret scan, including all CSV key values | exit 0 |

The final smoke report is `/tmp/value-investment-agent-staging-smoke-746c0b5-fresh.jsonl`.
It records only request metadata and these outcomes:

- Health, account registration, and login: `VERIFIED`.
- One asynchronous CSV batch: `expected_5`, `imported_5`, `duplicates_0`,
  `invalid_0`, and `retryable_0`.
- `key1` through `key5`: each live provider test returned `healthy` and was
  recorded as `VERIFIED`.
- AAPL workflow: ticker selection resumed, the valuation audit completed, and
  the run stopped at the pending valuation approval interaction. No
  deterministic calculation activity ran.
- Failover: `INCONCLUSIVE` with
  `requires_explicit_primary_fault_injection`; this acceptance does not inject
  a primary-key failure.

At the end of the run, `backend`, `frontend`, `llm-provider-service`,
`model-inference-news`, `model-inference-fls`, `postgres`, `redis`, and
`search-service` were `running/healthy`. `backend-migrations` exited with code
0. The scheduler profile was not started because it is optional and unrelated
to this deployment gate.

The secret scan passed against the Compose logs, the smoke report, the tracked
`.env.staging.example`, and the five real CSV key values. No raw key, password,
service token, or Fernet key was recorded in the report or logs.

## Coverage limits

This local acceptance proves the Compose deployment, internal service health,
bulk key import, real upstream inference health for all five supplied keys, and
the workflow approval boundary. It does not certify hosted TLS, reverse-proxy
headers/cookies, the optional scheduler, or key failover under an injected
provider fault. The run intentionally did not approve the valuation or execute
the deterministic calculation.

The setup and maintenance rules are in
[`docs/runbooks/staging-deployment.md`](../runbooks/staging-deployment.md).
