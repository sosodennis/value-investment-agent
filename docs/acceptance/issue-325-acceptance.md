# Issue 325 acceptance evidence

Status: incomplete. These checkpoints record live UI rejection and diagnostic
runs. They are not an acceptance or `VERIFIED` record.

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
- At the time of this earlier run, the Fundamental service project used only
  `docker-compose.issue280-operations.yml`; its running container had no SEC
  ingestion configuration. The application backend container had no
  `FUNDAMENTAL_SERVICE_URL` or `FUNDAMENTAL_SERVICE_TOKEN`, so that browser run
  could not be used as a service-backed acceptance run.
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
  request was observed because the run was stopped before service valuation.
  The open #327 issue tracks removal of the legacy Agent-owned SEC/report path
  after #325; this observation does not establish whether the #325 report falls
  back to it.
- Clicked `Cancel run` after observing the Agent-owned SEC fetch. The UI then
  showed `Run cancelled` at cursor 51 and `Connection closed`; it also showed
  the client-side `signal is aborted without reason` request alert.
- Docker inspection: app backend and Fundamental service both `healthy`;
  `curl -fsS http://127.0.0.1:18690/readyz` exited 0 and returned `ready`.
- `docker compose -p value-investment-agent-issue-325-app -f docker-compose.yml -f docker-compose.override.yml -f compose/verification/docker-compose.issue325-app-fundamental.yml config --services`
  exited 1 because this shell lacks `LLM_PROVIDER_ENCRYPTION_KEY`; no Compose
  resources were changed by this check.
- Result: **incomplete**. This run did not reach or verify the typed service
  facts path. No snapshot, fact IDs, or manifest digest from this run are
  acceptance evidence. Desktop/mobile viewports, keyboard evidence selection,
  and the evidence inspector remain unverified.

## Follow-up live run diagnostic

- Date: 2026-11-07 (local); backend log timestamps are 2026-11-06 UTC.
- Code under test: `3a333272508240f2ac7a6c2a8e7c0889131a58c4`.
- Base observed: `origin/main` at `55608191c13ad02a8efddc7079c54c71c702d8dc`.
- Route: `/workspace`, Personal organization, at `http://127.0.0.1:18681`.
- Run: `e2fb48bf-ed08-4a1d-84bf-03bc3d325869`; thread
  `thread_1794005945821`; report artifact
  `971d776e-2bab-49f3-a72a-21ce962d2156`.
- UI observation: the Fundamental workflow activity completed, but the report
  explicitly showed `Fundamental facts unavailable` and stated that the
  service did not provide a snapshot-bound fact set. No snapshot ID, fact IDs,
  manifest digest, or source hash was available to verify. The report showed
  summary values (revenue, net income, total assets, and ROE), while valuation
  metrics were unavailable. These values do not establish the required
  service-backed report binding.
- The overall run failure is separate: the Activity view showed
  `moderate-verdict` failed with code `failover_exhausted`. Backend logs for
  this exact run show the LLM provider returning `502 Bad Gateway` for Debate
  rounds and the final verdict, followed by `LLMProviderError` in
  `debate.orchestrator.run_verdict`. This explains the run's terminal failure;
  it does not explain or satisfy the missing Fundamental snapshot facts.
- The browser recorded `workflow sequence gap requires snapshot recovery` for
  this thread. The app backend, frontend, PostgreSQL, Redis, LLM provider,
  Fundamental service, and Fundamental PostgreSQL containers reported healthy;
  `/health` returned `{"status":"ok"}` and Fundamental `/readyz` returned
  `{"status":"ready","contract_version":"internal.v1"}`. During the
  run's UTC interval, the Fundamental service log showed no non-health request.
- The live containers were wired: the backend had both
  `FUNDAMENTAL_SERVICE_URL` and `FUNDAMENTAL_SERVICE_TOKEN` set, and the
  Fundamental service container was composed from both
  `docker-compose.issue280-operations.yml` and
  `docker-compose.issue312-sec-ingestion.yml`. This corrects the earlier
  checkpoint's environment state; the live failure was not caused by missing
  service URL/token or ingestion configuration.
- Source tracing found the request gap. The workspace calls
  `startWorkflowRun(threadId, { message: content })`; `RunRequest` makes
  `valuation_request` optional and no production Agent Core code constructs it.
  `read_service_valuation_input()` requires that typed input and runs before
  `client.execute()`. The root request therefore degrades before any service
  API call, consistent with the empty business-request log and the absent
  `fundamental_service` artifact projection.
- Read-only PostgreSQL counts in this issue's Fundamental project were:
  `snapshot_manifests=0`, `canonical_facts=0`, `snapshot_facts=0`,
  `data_release_manifests=0`, `release_manifests=0`, and
  `active_data_release_pointers=0`; the database had 10 model releases and 10
  policy releases. The service had no snapshot or active data release from
  which this run could resolve report facts.
- The Fundamental financial-health node separately logged a cache hit for its
  Agent-owned `sec_xbrl` payload and direct SEC archive GETs. Those legacy
  report values are the displayed summary metrics; they are not a substitute
  for service facts or evidence of same-snapshot valuation binding.
- Desktop/mobile viewport checks, keyboard fact selection, evidence-inspector
  provenance, and matching service snapshot/valuation trace remain unverified.
- Result: **incomplete**. The Debate LLM outage is a distinct observed
  run-failure cause. The Fundamental input was not supplied to the service
  flow, and the service had no snapshot or active release. The report facts
  remain unavailable and no service-backed snapshot evidence exists. No
  acceptance criterion is marked passed by this diagnostic.

## Next

Complete the owning-layer path that supplies a typed snapshot selector and
valuation context to Fundamental, and prepare a service-owned MSFT snapshot and
active release in this isolated acceptance project. Keep the Debate LLM 502
failure separate. Then complete the real service-backed report checks, viewport
and keyboard/evidence-inspector checks, and record all results against the
exact delivery commit.
