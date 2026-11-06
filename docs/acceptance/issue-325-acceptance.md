# Issue 325 acceptance evidence

Status: incomplete. This checkpoint records a live UI rejection and the
synthetic fixture that caused it. It is not an acceptance or `VERIFIED` record.

## Issue and checkpoint

- Issue: #325, open with the `blocker` label.
- Pull request: none.
- Branch: `codex/issue-325-fundamental-ui`, targeting `main`.
- Code under test: `574601bb6357243589653c3e2bdc151fbc9bc11d`.
- Base observed: `origin/main` at `55608191c13ad02a8efddc7079c54c71c702d8dc`.
- Docker projects: `value-investment-agent-issue-325-app` and
  `value-investment-agent-issue-325-fundamental`.

## Verification at this checkpoint

| Command or observation | Result |
| --- | --- |
| `npm run lint` in `frontend/` | exit 0 |
| `npm run typecheck` in `frontend/` | exit 0 |
| `npm run test -- --run` in `frontend/` | exit 0; 52 files, 288 tests passed |
| `uv run --project finance-agent-core pytest finance-agent-core/tests/agents/fundamental/test_fundamental_service_client.py finance-agent-core/tests/agents/fundamental/test_fundamental_service_cutover.py` | exit 0; 27 passed |
| `python3 scripts/architecture_guard.py` | exit 0 |
| `git diff --check` | exit 0 |
| `curl -fsS http://127.0.0.1:18690/readyz` | exit 0; `ready` |
| Docker container health | app frontend, backend, PostgreSQL, Redis, LLM provider, Fundamental service, and Fundamental PostgreSQL all healthy |
| `docker compose -p value-investment-agent-issue-325-app config --quiet` | exit 1; current shell has no `LLM_PROVIDER_ENCRYPTION_KEY`; existing containers remain healthy |

## Live route diagnostic

- Route: `/workspace?thread_id=02ad3c9c-3b25-4792-bfd1-d4c5825c8b5f&run_id=a3190b00-f3b3-4385-97cd-1784d214fdec` on `http://127.0.0.1:18681`.
- Artifact: `476799bc-bfec-40f8-b9de-821702018e41`, envelope
  `financial_reports/v1`; saved response SHA-256
  `6dca92d5944134832e7dcc121ad72c95b79265e460ff127acd761f20b5fd2f64`.
- The UI rendered the run summary and valuation preview, then showed
  `Full financial report unavailable` and `Fundamental facts unavailable`.
- Browser log reports
  `fundamental_output.artifact.data.fundamental_service.facts.facts[0].period_end must be a non-empty string.`
- The artifact stores each fact's period under nested `period` (`kind`,
  `start`/`instant`, `end`). The canonical `fundamental.v1` Agent contract
  exposes `period_start` and `period_end`; an instant date is available at
  `context.instant`, while the top-level `instant` field is optional.
  `service_valuation_flow.py` serializes the typed service model with
  `model_dump(mode="json")`.
- The artifact's `snapshot-issue325-live-1`, 64-character `a` digest, and
  `fact-revenue`, `fact-cash-zero`, `fact-liabilities-negative`,
  `fact-assets`, `fact-margin-missing`, and `fact-label` IDs are synthetic
  fixture values. Read-only counts in the matching Fundamental PostgreSQL
  project were zero for snapshot manifests, canonical facts, snapshot-fact
  links, active release pointers, release manifests, and source acquisition
  audits. This artifact is not evidence of a service-owned snapshot.
- The Fundamental service project currently uses only
  `docker-compose.issue280-operations.yml`; its running container has no SEC
  ingestion configuration. The application backend container has no
  `FUNDAMENTAL_SERVICE_URL` or `FUNDAMENTAL_SERVICE_TOKEN`, so the browser run
  cannot be used as a service-backed acceptance run.
- Viewports, keyboard selection, evidence inspector behavior, and a genuine
  service-backed workspace run are not yet verified.

## Follow-up live wiring attempt

- Date: 2026-11-07.
- Code under test: `fa98ad5e73abde612caf02f17c2253b8d11e45bc`.
- Route: `http://127.0.0.1:18681/workspace`, Personal organization.
- Action: entered `MSFT`, selected the exact `MSFT` / NASDAQ candidate shown at
  100% match over `MSFT.TO` at 90%, then continued from the actual workspace.
- Run: `21618609-ec4c-4994-adcc-2f5115c05945`; thread
  `thread_1794004480022`.
- The UI reached `fundamental_analysis / review-financial-health`. Backend logs
  show the Agent calling SEC archive URLs directly, including the 2025 MSFT
  10-K. Code inspection confirms `application/wiring.py` injects
  `fetch_financial_reports_payload` and `financial_health_flow.py` executes it
  before the service valuation stage.
- The Fundamental service container log contained only startup and `/readyz`
  health checks during this run; no service ingestion, snapshot, or fact-read
  request was observed. The run did not prove a service-backed report.
- Clicked `Cancel run` after observing the Agent-owned SEC fetch. The UI then
  showed `Run cancelled` at cursor 51 and `Connection closed`; it also showed
  the client-side `signal is aborted without reason` request alert.
- Docker inspection: app backend and Fundamental service both `healthy`;
  `curl -fsS http://127.0.0.1:18690/readyz` exited 0 and returned `ready`.
- `docker compose -p value-investment-agent-issue-325-app -f docker-compose.yml -f docker-compose.override.yml -f compose/verification/docker-compose.issue325-app-fundamental.yml config --services`
  exited 1 because this shell lacks `LLM_PROVIDER_ENCRYPTION_KEY`; no Compose
  resources were changed by this check.
- Result: **failed / incomplete**. The live workflow still reaches a legacy
  Agent-owned SEC acquisition before it can exercise the typed service facts
  path. No snapshot, fact IDs, or manifest digest from this run are acceptance
  evidence. Desktop/mobile viewports, keyboard evidence selection, and the
  evidence inspector remain unverified.

## Next

Resolve the workflow's Agent-owned SEC fetch and service-stage ordering against
the #312 service ownership contract before another live run. Then verify the
real workspace artifact's fact IDs, snapshot ID, and manifest digest against
the valuation trace. Run desktop and mobile route checks, keyboard evidence
selection, the evidence inspector, and the remaining issue acceptance criteria
before updating this record for the exact delivery commit.
