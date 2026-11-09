# Issue #353 Acceptance Record

Issue: [#353](https://github.com/sosodennis/value-investment-agent/issues/353)

## Scope

The Fundamental Service now prepares bounded Monte Carlo controls for automatic
`fcff_dcf` and `transition_fcff_dcf` valuation inputs. The service owns the
uncertainty policy, deterministic seed derivation, empirical-history versus
policy-prior provenance, invalid-draw disposition, result hashing, and the
`p05`/`p50`/`p95` Bear/Base/Bull contract. Search, LLM extraction, company
guidance, and analyst forecasts remain outside the default path.

Automatic preparation remains `provisional` while the history threshold is not
validated. It does not claim calibrated prediction-interval semantics. A
manual assumption override rebuilds the service-owned uncertainty spec and
therefore changes the input digest and seed.

## Verified commits

| Commit | Purpose |
| --- | --- |
| `85311c211ed1baf943dd42dab49d89789eefe5de` | Distribution provenance contract checkpoint |
| `ee6a8416e6e1904909c0abe0eeddde4be32dc2ee` | Automatic service-owned policy checkpoint |
| `ad2b6fd689274cd2dc3c97acb71eef02aefe8b69` | Monte Carlo execution, report hashing, and caller projection checkpoint |

The final code verification target before this record was
`ad2b6fd689274cd2dc3c97acb71eef02aefe8b69`.

## Checks

| Check | Result |
| --- | --- |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests -q` | exit 0; 293 passed, 25 skipped, 1 existing Pydantic serializer warning |
| `uv run --project finance-agent-core pytest finance-agent-core/tests/agents/fundamental -q` | exit 0; 60 passed |
| `uv run --project finance-agent-core ruff check finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/service_valuation_flow.py` | exit 0; all checks passed |
| `uv run python scripts/architecture_guard.py` | exit 0; no boundary violations |
| `uv run --project fundamental-service python -m compileall -q fundamental-service/src/fundamental_service` | exit 0 |
| Focused default-policy and uncertainty tests | exit 0; covered both FCFF families, empirical/prior provenance, deterministic seed/result hash, invalid-draw accounting, and manual override reseeding |

## Docker verification

Compose project: `value-investment-agent-353-monte-carlo`

Host ports: PostgreSQL `18654`, Fundamental Service `18655`.

| Check | Result |
| --- | --- |
| `docker compose -p value-investment-agent-353-monte-carlo -f compose/verification/docker-compose.issue280-operations.yml config --quiet` | exit 0 |
| `docker compose ... up -d --build` | exit 0; PostgreSQL healthy and Fundamental Service started |
| `docker compose ... ps` | both containers healthy |
| `curl -fsS http://127.0.0.1:18655/readyz` | exit 0; `status=ready`, `contract_version=internal.v1` |
| `curl -fsS http://127.0.0.1:18655/openapi.json` schema inspection | exit 0; report hash, quantile contract, and distribution provenance fields present |

The container was not seeded with a release-bound SEC snapshot, so a full
HTTP valuation request/result replay was not run against the empty Docker
database. The service-backed automatic calculation path is covered by the
Fundamental Service integration tests listed above.

## Remaining work

- Independent out-of-sample calibration is still required before any result can
  be labelled `verified` for prediction-interval semantics.
- The optional Search/LLM evidence reference path remains scoped to #355.
