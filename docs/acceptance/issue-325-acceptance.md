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

## Request producer contract audit

- Date: 2026-11-07.
- Status: **blocked; acceptance incomplete**.
- Issue: #325 remains open with the `blocker` label. No pull request exists.
- Branch: `codex/issue-325-fundamental-ui`, based on `main`.
- Code under test: `94ddafe68ac1005b64f72cf6a126cf63cde5cc4e`.
- The workspace submits only `{ message }` from `frontend/src/hooks/useAgent.ts:86`.
  `RunRequest.valuation_request` is optional in
  `finance-agent-core/src/analysis_runtime/interface/routes.py:70-74`.
  No production Agent Core path constructs the typed request.
- `CompanyProfile` contains a ticker and descriptive market fields, but no CIK,
  in `finance-agent-core/src/shared/cross_agent/domain/market_identity.py:6-15`.
  The profile provider also omits CIK in
  `finance-agent-core/src/agents/intent/infrastructure/market_data/company_profile_provider.py:34-43`.
- Snapshot resolution requires a full `IdentityV1` in
  `fundamental-service/src/fundamental_service/contracts.py:427-436`.
  SEC ingestion requires both a CIK and identity, then checks that the CIK
  matches `identity.issuer_id` in `contracts.py:598-640`. The current workspace
  state cannot supply those fields through the existing typed path.
- `run_service_valuation_flow()` validates `valuation_request` before its first
  `client.execute()` call in
  `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/service_valuation_flow.py:997-1044`.
  Missing request data therefore degrades before the Fundamental service
  receives a business request.
- The service has a separate `calculate-with-policy` endpoint, but the Agent
  client exposes only the `validate` and `calculate` operations in
  `finance-agent-core/src/agents/fundamental/infrastructure/fundamental_service_client.py:39-47`.
  The current Agent flow accepts a fully populated valuation input. It has no
  production request producer that obtains the required issuer identity,
  snapshot, and policy-bound assumptions.
- Do not infer a CIK from the ticker, reuse Agent-owned SEC reports as service
  facts, or fabricate a snapshot selector. The owning service contract must
  provide a verified issuer-identity path before the workspace can construct
  a valid request.

### Verification at this checkpoint

Source-code checks below ran against commit
`94ddafe68ac1005b64f72cf6a126cf63cde5cc4e`. Docker health commands report the
running acceptance environment at this checkpoint.

| Command | Result |
| --- | --- |
| `uv run pytest tests/agents/fundamental/test_fundamental_service_client.py tests/agents/fundamental/test_fundamental_service_cutover.py -q` from `finance-agent-core/` | exit 0; 27 passed |
| `uv run ruff check src api` from `finance-agent-core/` | exit 0 |
| `python3 scripts/architecture_guard.py` from the repository root | exit 0 |
| `npm run lint` from `frontend/` | exit 0 |
| `npm run typecheck` from `frontend/` | exit 0 |
| `npm run test -- --run` from `frontend/` | exit 0; 52 files and 288 tests passed |
| `git diff --check` | exit 0 |
| `docker compose -p value-investment-agent-issue-325-app ps` | exit 0; backend, frontend, PostgreSQL, Redis, and LLM provider healthy |
| `docker compose -p value-investment-agent-issue-325-fundamental ps` | exit 0; Fundamental service and PostgreSQL healthy |
| `curl -fsS http://127.0.0.1:18690/readyz` | exit 0; `ready` |

- No pull request exists, so no PR CI result is available.
- No new workspace run was started at this checkpoint. The earlier run recorded
  above still has no service snapshot, fact IDs, or manifest digest.
- Desktop/mobile rendering, keyboard selection, evidence-inspector provenance,
  and exact snapshot-to-valuation trace binding remain unverified.
- The previous Debate LLM 502 remains a separate observed failure. This audit
  does not test or attribute that outage.
- Result: the focused code checks and Docker health pass. The typed request
  producer and service-backed workspace acceptance remain blocked. No acceptance
  criterion is marked passed by this checkpoint.

## Next

Add a service-owned, verifiable issuer-identity path and wire it through the
typed Agent client and request producer. Then prepare an MSFT service snapshot
and active release in the isolated acceptance project. Run the real workspace
route and complete the desktop, mobile, keyboard, and evidence-inspector checks.
Record the results against the exact delivery commit.

## Identity contract ownership confirmation

- Date: 2026-11-07.
- Audit commit: `8147dd14f2259f9601aae344083c2cb939957ad8`.
- The merged Fundamental contract requires a full `IdentityV1` for snapshot
  resolution. SEC ingestion additionally requires a ten-digit `cik`, a ticker,
  and an identity whose `issuer_id` normalizes to that CIK. The service checks
  that the requested ticker is registered to the SEC issuer, but exposes no
  ticker-to-issuer identity-resolution operation.
- The Agent client operation map exposes ingestion, snapshot resolution, facts,
  validation, calculation, uncertainty, and replay. Its existing profile source
  supplies a ticker and descriptive fields only; it does not provide the CIK or
  the complete security identity required by the service contract.
- The #312 issue contract explicitly says a ticker alone is not a sufficient
  identity key and requires the caller to provide canonical issuer/security
  identity and CIK. Therefore, adding a caller-side field or treating a ticker
  as a CIK would not resolve the missing ownership boundary.
- Conclusion: a service-owned issuer-identity resolution contract is a required
  prerequisite to #325's live workspace acceptance. This work is outside the
  current #325 report-display scope and must be tracked as a linked blocker
  before any service-side implementation is added. Blocker #336 now tracks
  that contract and explicitly blocks #325. #325 remains open and incomplete;
  no live valuation request was sent during this audit.
- Evidence locations: `fundamental-service/src/fundamental_service/contracts.py`
  (`IdentityV1`, `SnapshotResolutionRequestV1`, and `SecIngestionRequestV1`),
  `fundamental-service/src/fundamental_service/source_acquisition.py` (SEC
  ticker/issuer validation), `finance-agent-core/src/agents/fundamental/infrastructure/fundamental_service_client.py`
  (supported operations), and
  `finance-agent-core/src/shared/cross_agent/domain/market_identity.py`
  (`CompanyProfile`).

## Resumption audit and live handoff

- Date: 2026-11-07.
- Main and `origin/main`: `809d42d96b625440c38e9e6b51c63a878884eda8`;
  GitHub's current `main` API response matched.
- Issues #328, #312, and #321 are closed with `VERIFIED`; #325 remains open
  with the `blocker` label and has no pull request. Blocker #336 is closed.
- Relevant merged PRs target `main`: #329 (`10a88e41f3f5d63ec9feebb472dbd4d5469c647f`),
  #332 (`eb4cdd5c597e08743aaaf845c4ed27227b9dff5a`), #334
  (`bfb5c22912c0e344f83814af154fcfadda29e45c`), #335
  (`55608191c13ad02a8efddc7079c54c71c702d8dc`), and #337
  (`809d42d96b625440c38e9e6b51c63a878884eda8`). GitHub reported the
  Monorepo Contract Gates workflow successful for each listed merge SHA.
- Current worktree: `codex/issue-325-fundamental-ui`, clean at
  `3b2233d43b766097aa729c0a4c46cefa5da156d2`, based on the current main SHA.
  No CI run exists for this local-only head.
- Checks previously completed on this exact code SHA: `npm run lint` (exit 0),
  `npm run typecheck` (exit 0), `npm run test -- --run` (exit 0; 52 files,
  293 tests), focused Fundamental report tests (exit 0; 9 tests), and
  `git diff --check` (exit 0).
- Both isolated Compose configurations passed `config --quiet` (exit 0):
  `value-investment-agent-issue-325-app` using the root Compose file, override,
  and `compose/verification/docker-compose.issue325-app-fundamental.yml`;
  `value-investment-agent-issue-325-fundamental` using
  `docker-compose.issue280-operations.yml` and
  `docker-compose.issue312-sec-ingestion.yml`. Pinned SEC taxonomy, EDGAR,
  Xule, and DQC bind mounts were resolved from the existing service container.
- Before rebuilding, all seven containers in those projects reported healthy.
  Their app backend and Fundamental service images predate this worktree head;
  neither service has a host source bind mount. No route, snapshot, or database
  result from those images is evidence for the current commit.
- The current workspace hook sends only `{ message }`; the typed run contract
  accepts an optional `valuation_request`. Static inspection confirms that,
  when a complete caller request is absent, the Agent producer returns a
  `facts_only` artifact and does not create assumptions or a valuation trace.
  The #336 identity resolver is now on main, but a live request must still
  establish whether the required caller-owned valuation input is available.

### Next

Rebuild only the issue-325 backend, frontend, and Fundamental service from this
worktree while retaining both PostgreSQL volumes. Then exercise the real
workspace route and inspect the service-owned snapshot, facts, and valuation
trace. If the route cannot provide the required caller assumptions, record the
remaining owning-layer gap as a linked `blocker`; leave #325 incomplete.

## Exact-commit rebuild and live route diagnostic

- Date: 2026-11-07.
- Code under test: `38b5def58d23a887e58f13e41ff3fb4221b76df2`.
- Compose config was rechecked before mutation with `docker compose ... config
  --quiet` (exit 0) for both isolated projects. The app project used
  `docker-compose.yml`, `docker-compose.override.yml`, and
  `compose/verification/docker-compose.issue325-app-fundamental.yml`; the
  Fundamental project used `docker-compose.issue280-operations.yml` and
  `docker-compose.issue312-sec-ingestion.yml`.
- Exact build commands and results: app `backend` build (exit 0), app
  `frontend` build (exit 0; Next.js production compile and TypeScript passed),
  and Fundamental `fundamental-service` build (exit 0; pinned Arelle 2.47.4
  installed). Only the three required service images were rebuilt.
- `docker compose ... up -d backend frontend` and `docker compose ... up -d
  fundamental-service` exited 0. The existing app and Fundamental PostgreSQL
  volumes were retained; no `down --volumes` or global cleanup ran.
- New container health: app frontend, backend, PostgreSQL, Redis, and LLM
  provider healthy; Fundamental service and PostgreSQL healthy. Fundamental
  `/readyz` returned `{"status":"ready","contract_version":"internal.v1"}`.
  The rebuilt image digests were recorded locally as app backend
  `sha256:19453b8732b51356f0969425f9d9da9682e14e4d3c1244fadca91bc08a9e14`,
  Fundamental service
  `sha256:0ab5795055d7ee14126010ae491af6e8a529e3d4595cb58614f74380d21e32db`,
  and frontend
  `sha256:ff151e6d37cd7e6cb2d7056f21c531e8e53cc3e9d1873c40dbbc3facd39dbe31`.
- Route: `http://127.0.0.1:18681/workspace`, Personal organization, account
  `issue325-live-20261107@example.test`, desktop browser session. Entered
  `MSFT`, selected `MSFT / Microsoft Corporation / NASDAQ / 100% match` over
  `MSFT.TO / Toronto / 90%`, and continued with the selected company.
- Run: `6931b7df-38e3-4ee9-aca6-b8eb1283c7e8`; thread
  `thread_1794020551914`. The activity view reached
  `fundamental_analysis / review-financial-health`, while technical and news
  subgraphs completed. The backend log for this exact run shows direct
  `data.sec.gov` and `www.sec.gov/Archives` requests from Agent-owned
  `sec_xbrl`; the Fundamental service log contains only startup, health probes,
  and one earlier intentionally malformed resolver probe (`400 invalid_request`).
- The run was cancelled from the workspace after the legacy health node kept
  traversing historical SEC filings. The browser visibly reported `Run
  cancelled`, `cancelled`, cursor 51, and `Connection closed` (exit is a UI
  observation, not a shell command). No service-backed snapshot, fact IDs,
  manifest digest, valuation trace, or evidence inspector result was produced.
- Immediate Fundamental PostgreSQL counts after cancellation were all zero:
  `snapshot_manifests`, `canonical_facts`, `snapshot_facts`,
  `release_manifests`, `active_data_release_pointers`, and
  `sec_ingestion_acquisitions`. This run therefore cannot satisfy any
  service-backed acceptance criterion.

### Diagnostic result

**Incomplete and blocked.** The exact-commit containers are healthy, but the
real workspace route still performs a long Agent-owned SEC financial-health
fetch before the service valuation stage. The UI run was cancelled before any
service ingestion or facts projection. Do not mark #325 `VERIFIED`, merge it,
or close it. The remaining gap is in the owning Agent workflow/request
producer: it must reach the typed Fundamental service path with caller-owned
valuation input without substituting legacy SEC report data.

### Linked blocker record

- Existing issue #327 owns removal of active Agent Core legacy reports,
  fixtures, and direct SEC/report fallback paths. It was previously open
  without a blocker label.
- On 2026-11-07, #327 was labeled `blocker` and received comment
  `https://github.com/sosodennis/value-investment-agent/issues/327#issuecomment-6701466961`
  with the exact run, log, and zero-row Fundamental DB evidence above. This
  records the acceptance compromise in the owning layer; no workaround or UI
  concealment was added.
- The same incomplete result was recorded on #325 at
  `https://github.com/sosodennis/value-investment-agent/issues/325#issuecomment-6701490193`;
  #325 remains open with the `blocker` label and no pull request.

## Exact-head diagnostic after #336

- Date: 2026-11-07.
- Code under test: `58c373d955628e56cabeebb51210c8c6dcb699aa`, branch
  `codex/issue-325-fundamental-ui`, based on `origin/main` at
  `9c70bf0da054f528661c7b501e627e0a22aaa3c0`.
- Compose projects: `value-investment-agent-issue-325-app` and
  `value-investment-agent-issue-325-fundamental`. The app backend/frontend
  images were rebuilt as `sha256:19453b8732b51356b8f0969425f9d9da9682e14e4d3c1244fadca91bc08a9e14`
  and `sha256:ff151e6d37cd7e6cb2d7056f21c531e8e53cc3e9d1873c40dbbc3facd39dbe31`;
  the Fundamental service image was rebuilt as
  `sha256:0ab5795055d7ee14126010ae491af6e8a529e3d4595cb58614f74380d21e32db`.
- Compose `config --quiet` passed for both projects. Backend `/health`,
  Fundamental `/readyz`, and all required containers were healthy. Existing
  PostgreSQL volumes were retained; no volume deletion or global cleanup ran.
- Route: `http://127.0.0.1:18681/workspace`, Personal organization, account
  `issue325-live-20261107@example.test`. Entered `MSFT`, selected
  `MSFT / Microsoft Corporation / NASDAQ / 100% match` over `MSFT.TO / Toronto /
  90%`, then continued from the real workspace.
- Run: `755b4261-df3d-4997-8205-0056a1813385`; thread
  `thread_1794034417085`. The activity reached
  `fundamental_analysis / review-financial-health`. Backend logs for this run
  show `fundamental_xbrl_payload_cache_hit` from the Agent-owned `sec_xbrl`
  financial payload path. The Fundamental service log contains only health
  probes; no business request was received.
- The run was cancelled after the legacy financial-health path continued. The
  browser showed `Run cancelled`, `cancelled`, cursor `51`, and `Connection
  closed`, with the client alert `signal is aborted without reason`.
- Fundamental PostgreSQL counts after cancellation were all zero:
  `snapshot_manifests=0`, `canonical_facts=0`, `snapshot_facts=0`,
  `release_manifests=0`, `active_data_release_pointers=0`, and
  `sec_ingestion_acquisitions=0`.
- Desktop route observation used viewport `1440x900`; mobile observation used
  `390x844`. Both showed the cancelled/degraded state. The evidence inspector
  showed `0 items` and no report value was selectable, so keyboard evidence
  selection and provenance inspection could not be verified.

### Diagnostic result

**Incomplete and blocked.** #336 provides issuer identity and the #325 branch
contains a typed service request producer, but the live workspace still enters
the old Agent-owned SEC/report financial-health path before reaching service
valuation. This run is evidence for the owning #327 cleanup blocker only; it
does not satisfy any service-backed #325 acceptance criterion and must not be
used to mark #325 `VERIFIED`, merge it, or close it.

The exact cleanup checkpoint that must be applied before the next live run is
PR #340 branch `codex/issue-327-legacy-cleanup`, currently at
`cfadb22e4779256ba22d3af6b708ad3fd66b38af`.

## Exact mapping boundary probe

- Date: 2026-11-07.
- Code under test: `ac456d070103d910004d99a0cd1441dc70179091`, branch
  `codex/issue-325-fundamental-ui`.
- Compose project: `value-investment-agent-issue-325-fundamental`; the
  Fundamental service and PostgreSQL containers were healthy and
  `/readyz` returned HTTP 200.
- A signed `internal.v1` `POST /v1/identity/resolve` for `MSFT` using the
  Personal organization `43f50f0f-c6ff-4fb2-b4d2-ed366bc55613` returned HTTP
  200 and resolved CIK `0000789019`, US-GAAP, and USD.
- The following signed `POST /v1/data/ingestions` used the exact producer
  request shape: required fields `revenue`, `operating_income`, `cash`,
  `debt`, and `diluted_shares`, mapping IDs `sec-us-gaap-v1-<field>`, the
  pinned `2.47.4` / `sec-efm-us-dqc-v31.0.3` runtime, and the installed
  `sec-us-gaap-2023-2024-public-bundle` taxonomy. It returned HTTP 422 with
  stable code `FACT_MAPPING_UNRESOLVED` and message
  `requested mapping release is unavailable`.
- The Fundamental PostgreSQL database had zero `mapping_decisions`,
  `sec_ingestion_acquisitions`, `snapshot_manifests`, `canonical_facts`,
  `snapshot_facts`, `release_manifests`, and `active_data_release_pointers`.
  The source audit recorded the identity resolution and the failed ingestion
  correlation `issue325-debug-ingestion-20261107-2`.

### Diagnostic result

**Incomplete and blocked.** The signed identity boundary and pinned SEC
runtime are reachable, but the producer's mapping IDs have no corresponding
service-owned mapping records in the disposable verification database. No SEC
filing was acquired and no snapshot or fact was published. The next checkpoint
must provision the canonical mapping release through the Fundamental-owned
metadata path, then rerun the same request before changing application code.

### Single-field parser control

- Date: 2026-11-07.
- Reused the same healthy service, disposable Fundamental database, pinned
  validation runtime, taxonomy bundle, and 2024 MSFT 10-K accession above.
- Sent a signed ingestion request for only `revenue`, using the published
  `sec-us-gaap-v1-revenue` mapping and a 130-second request deadline.
- Correlation ID: `issue325-debug-revenue-20261107-1`; acquisition key:
  `efd6824baadee5103581382a0eba621fea46d64db2b9fe3626276d0df59496c8`.
- The service returned HTTP 422 `XBRL_PARSE_FAILED` after 8.08 seconds with
  `offline SEC parser exited without a result`. The source audit persisted
  that outcome; `sec_ingestion_acquisitions`, snapshots, and canonical facts
  remain empty for this attempt.

### Diagnostic result

**Incomplete and blocked.** Mapping lookup succeeds for the single-field
control, but the offline parser worker exits before returning a parse result.
The failure is not caused by the number of requested mappings. The worker's
exit cause remains undetermined; inspect its resource limit and retained parser
inputs before any service or application code change.

## Parser worker cgroup OOM replay

- Date: 2026-11-07.
- Code under test: `eeb33c3b8beb78aaf93b10afb6315609f99bb355` on
  `codex/issue-325-fundamental-ui`, with `origin/main` at
  `08afd4660bd98d999d76d5ea9b7424cd30adc34c`.
- Compose project: `value-investment-agent-issue-325-fundamental`.
  The Fundamental service container was
  `value-investment-agent-issue-325-fundamental-fundamental-service-1`; its
  configured cgroup limit was `536870912` bytes (512 MiB).
- The disposable PostgreSQL volume was provisioned with the already verified
  `sec-revenue-v1` mapping (`mapping_digest`
  `21b8aaccbfd32095c6b39489632358ca122d8bc343505da21b6cb60e0c02615b`) so
  this replay reached the parser. No records were deleted or reset.
- A signed `internal.v1` request used MSFT CIK `0000789019`, accession
  `0000950170-24-087843`, valuation cutoff `2025-06-30T00:00:00Z`, one
  required field (`revenue`), and a unique policy version. Correlation ID was
  `issue325-oom-replay-20261107-3`.
- A 200 ms host monitor recorded service RSS from `185.3 MiB` to `461.6 MiB`
  of `512 MiB` while the request was active. The API returned HTTP 422 after
  `9.006799` seconds with `XBRL_PARSE_FAILED` and
  `offline SEC parser exited without a result`.
- The same request shape was replayed with correlation ID
  `issue325-oom-replay-20261107-4`. The cgroup counters changed from
  `oom=4`, `oom_kill=4`, `memory.peak=536870912` to `oom=5`, `oom_kill=5`,
  `memory.peak=536870912`; the container stayed `running` with
  `restarts=0`. The API returned HTTP 422 after `8.47894` seconds with the
  same parser error.
- The PostgreSQL source audit persisted both parser outcomes as
  `XBRL_PARSE_FAILED` with no source hashes. After the replays,
  `sec_ingestion_acquisitions`, `snapshot_manifests`, and `canonical_facts`
  remained zero. The temporary monitor/request artifacts were
  `/tmp/issue325-memory-monitor-325.uUWrjU`,
  `/tmp/issue325-oom-before.llVYAd`, `/tmp/issue325-oom-after.MsUBDy`, and
  `/tmp/issue325-ingestion-request-325b.VyHIqK`.

### Diagnostic result

**Incomplete and blocked.** The parser worker is killed by the Fundamental
service cgroup at its 512 MiB limit while parsing this accession. The service
process remains alive, but it receives no parser result and fails closed before
publishing an acquisition, snapshot, or canonical fact. This is a
Fundamental service/runtime blocker; the UI must not conceal it. The next
checkpoint must make the parser resource budget and child-process failure
observable and provide a bounded runtime fix, then rerun this exact replay.

## Exact-head bounded parser replay

- Code checkpoint: `2e035b194f42d9cb9aa03d27873f5e3bbcdf9165`.
- Compose project: `value-investment-agent-issue-325-fundamental`; the rebuilt
  Fundamental image was
  `sha256:dd673ecb034adba4447f1e4666b65719b10b5aab3c5055c00918da698c542314`.
  PostgreSQL host port was `18691` and Fundamental service host port was
  `18690`.
- The verification Compose memory limit resolved to `1073741824` bytes (1 GiB)
  from `FUNDAMENTAL_SERVICE_MEMORY_LIMIT=1g`. Both PostgreSQL and Fundamental
  service containers were `healthy`; `/livez` and `/readyz` returned HTTP 200.
- A signed request for MSFT CIK `0000789019`, accession
  `0000950170-24-087843`, one `revenue` mapping, and correlation ID
  `issue325-oom-fixed-replay-20261107-1` completed in `20.496562` seconds.
  It returned HTTP 200 with `status=created`, `quality_status=verified`, 57
  canonical fact IDs, snapshot
  `snapshot-7d3614b0c9f4007f24af408f3aca234d`, and manifest digest
  `10972fb6f3879c771c9cc830f5816cf719d9d61d1a777c94488d2f807e635269`.
- The parser issue codes were the previously observed non-blocking
  `EFM.5.02.05.14.hidden-fact-eligible-for-transform`, `EFM.6.05.42`, and
  `ixbrl:selfClosedTagWarning`; no blocking finding was returned.
- cgroup counters remained `oom=0`, `oom_kill=0`, and
  `oom_group_kill=0`; `memory.peak` was `728510464` bytes (approximately
  694.8 MiB), below the 1 GiB limit. The container stayed running with
  `oom=false` and `restarts=0`.
- PostgreSQL counts after the replay were two acquisitions, two snapshot
  manifests, and 114 canonical facts. The earlier failed attempts remain
  audit-only and did not publish facts.
- The full Fundamental service suite at this exact code checkpoint returned
  `253 passed, 2 skipped, 1 warning` in `119.48s`. The skips are the existing
  runtime-gated parser tests without their optional pinned environment; the
  live replay above exercised the configured runtime path.

### Diagnostic result

**Runtime blocker resolved; issue acceptance remains incomplete.** The service
now has a bounded, configurable parser budget that is sufficient for the
pinned Microsoft replay, and the same request publishes a verified immutable
snapshot without cgroup OOM. The remaining #325 work is the Agent-to-service
request producer and real workspace route acceptance, including same-snapshot
fact/valuation trace, desktop/mobile UI, keyboard operation, and evidence
inspector verification.

## Exact combined service identity boundary probe

- Date: 2026-11-07.
- Combined source: #325 `a9df879656be5673a38152fe1226776362c36b73` with the
  #327 cleanup tree merged without commit; the detached verification tree was
  `/Users/denniswong/.codex/worktrees/issue-325-327-acceptance-v2`.
- Compose projects were isolated as
  `value-investment-agent-325-327-acceptance-app` and
  `value-investment-agent-325-327-acceptance-fundamental`. Backend image digest
  was `sha256:1f96b0ff50771869094b9676de0e3dbffaeb8786ae5bb5596e632eb5e806c7fc`,
  frontend was
  `sha256:fadb3a2101124ee08d47c729f339d47933d9c0c55c7b67cbd7f31e0c339a7a02`,
  and Fundamental service was
  `sha256:7a89e2865e7a6c435fbc863fa19302080b28a5c580d160ea952835744cd3b483`.
  `GET http://127.0.0.1:18780/health` and
  `GET http://127.0.0.1:18790/readyz` returned HTTP 200; all required
  containers were healthy.
- A signed `internal.v1` `POST /v1/identity/resolve` for `MSFT` reached the
  service with principal `issue-325-acceptance`, organization
  `org-sec-ingestion-test`, and correlation ID
  `issue-325-live-msft-identity`. It returned HTTP 422
  `ISSUER_IDENTITY_UNSUPPORTED` with the stable message
  `SEC companyfacts does not establish USD reporting`.
- The service persisted the three SEC source captures before validation. The
  audit outcome was `ISSUER_IDENTITY_UNSUPPORTED`, with source hashes
  `76b4b2abb9f7dd0e9cff38e2f20336952bb41806057b2dd1033e244f3e1faec2`,
  `1a4256a23be814a5193601a2c733d1da647c45da4d73dfe98eee58e32f8f9251`, and
  `8c1903c041f5c27e86ed15f37debb1f41882b7904bba129ef9edc76478b1e8ea`.
  Direct inspection of the latter SEC companyfacts capture found 562 US-GAAP
  concepts with USD units and three historical EUR observations for
  `DebtInstrumentFaceAmount`; the issuer is not missing USD reporting.
- A control request for `AAPL` on the same service returned HTTP 200 with CIK
  `0000320193`, Apple Inc., US-GAAP/USD, source hashes
  `76b4b2abb9f7dd0e9cff38e2f20336952bb41806057b2dd1033e244f3e1faec2`,
  `0b0e61bf3ab6ea0c33a95bca99be8defad712262d378282d6e9e343856548fae`, and
  `f085735b4d08fb116ade18d24247ffabe11df8eb52eae6556b165831f15ef1ad`, and
  resolution digest
  `bc50f34c93d65fdf421fb8729946594d3f28032e2e10908ef1cbdee2bd8f1b91`.
- Fundamental PostgreSQL remained empty after both probes:
  `snapshot_manifests=0`, `canonical_facts=0`, `snapshot_facts=0`, and
  `sec_ingestion_acquisitions=0`. No ingestion, snapshot, valuation trace, or
  UI evidence was claimed.

### Diagnostic result

**Incomplete and blocked.** The combined service is reachable and the signed
identity boundary is exercised, but the merged #336 resolver rejects a valid
USD-reporting issuer solely because its companyfacts includes unrelated
historical EUR facts. This is an owning Fundamental identity-policy defect,
not a browser workaround or an SEC fallback opportunity. A linked blocker is
required before the MSFT service-backed acceptance can proceed. Blocker #341
tracks the service-owned policy fix and is linked to #336 and #325.

## Exact MSFT identity, ingestion, and release boundary probe

- Date: 2026-11-07.
- Code under test: #341 checkpoint `ea4f4264`; the isolated Fundamental image
  was `sha256:98f4fffb33403bc0ee2a46f6971b4e86dc7997c7abc5d78e987576943cd5fbcb`.
  The service project was `value-investment-agent-341-msft-identity` with
  PostgreSQL on `18797` and the service on `18796`; both containers were
  healthy and `/readyz` returned `{"status":"ready","contract_version":"internal.v1"}`.
- Signed `POST /v1/identity/resolve` for `MSFT` returned HTTP 200 with issuer
  `0000789019`, `MICROSOFT CORP`, US-GAAP/USD, resolution digest
  `ccd17e08802ee2216c0d751f2407a77421e7943ea3dffc57f16bdf17847e4cf4`, and the
  SEC source hashes already recorded for the corrected identity path.
- Signed `POST /v1/data/ingestions` with accession
  `0000950170-24-087843`, valuation cutoff `2025-06-30T00:00:00Z`, and the
  approved `sec-revenue-v1` mapping returned HTTP 200 `status=created`,
  `quality_status=verified`, snapshot
  `snapshot-23146d7e2b74d2d512cbc714181c1192`, manifest digest
  `d77bfbd757323f330de38b69aea03ca4a742b88818becc0f799d98d92c9b2311`,
  validation profile digest
  `639140b39584b3ee3276f09a011403dec911efe41ea1b98773f5f770bd5200d4`, and
  57 canonical fact IDs. Reported parser issue codes were
  `EFM.5.02.05.14.hidden-fact-eligible-for-transform`, `EFM.6.05.42`, and
  `ixbrl:selfClosedTagWarning`; no blocking finding was reported.
- An immutable release candidate was published and activated through the
  authenticated release routes. Profile `sec-public-pit-msft-issue341` was
  active at revision 1 with manifest digest
  `846c625f1d051260a6016e4f948911edc5710d4bde05388df0c4c610c48edd15`.
- Signed `POST /v1/data/snapshots/resolve` for that profile and the same MSFT
  identity returned HTTP 422 `FACT_CONFLICT` with
  `canonical fact selection is not verified for this snapshot`. The 57 facts
  all use the normalized field `revenue`; they include both the consolidated
  dimensionless total and product/geography dimensional facts at the same
  availability timestamp. No Agent or browser fallback was used.

### Diagnostic result

**Incomplete and blocked.** The identity, ingestion, immutable snapshot, and
release activation boundaries now execute with real SEC data. Field-level
snapshot resolution still fails closed because the ingestion publication keeps
segment facts under the same normalized field without selecting the unique
consolidated fact for this request. Blocker #342 tracks the service-owned
selection fix and is linked to #312, #321, and #325.

## Exact live workspace producer and filing-compatibility probe

- Date: 2026-11-07 (local); the app route was
  `http://127.0.0.1:18681/workspace` in the Personal organization.
- Code under test: `e05300d6a46277fa76ab46562e4b10ab56d0b43c` on
  `codex/issue-325-fundamental-ui`.
- Compose projects were isolated as `value-investment-agent-issue-325-app`
  and `value-investment-agent-issue-325-fundamental`. Backend, frontend,
  PostgreSQL, Redis, LLM provider, Fundamental service, and Fundamental
  PostgreSQL were healthy; `GET http://127.0.0.1:18690/readyz` returned HTTP
  200 with `{"status":"ready","contract_version":"internal.v1"}`.
- A fresh workspace run `436d527c-4cf3-48f2-87b0-7e0fe429d421` reached the
  actual ticker clarification. The operator selected `MSFT Microsoft
  Corporation NASDAQ` at 100% match over `MSFT.TO` at 90%. Fundamental
  activities `review-financial-health`, `select-model`, and
  `calculate-valuation` ran through the service cutover path; no Agent-owned
  SEC fetch was observed.
- The service accepted the signed identity request for organization
  `43f50f0f-c6ff-4fb2-b4d2-ed366bc55613` and returned HTTP 200. The following
  service ingestion request used the producer's five required fields and
  approved `sec-us-gaap-v1-*` mappings, but default filing selection returned
  HTTP 422 `DQC_VALIDATION_UNAVAILABLE` (`DQC rules did not run`). The current
  runtime has a pinned 2023–2024 taxonomy/DQC bundle while the 2026 valuation
  cutoff selects a 2026 MSFT filing. No snapshot or canonical facts were
  published for this live run; the PostgreSQL audit recorded outcome `failed`.
- A control request with the same signed context and the same five required
  fields, pinned to the already verified MSFT accession
  `0000950170-24-087843`, returned HTTP 200 `status=created`,
  `quality_status=verified`, 57 canonical fact IDs, snapshot
  `snapshot-c53955e8dec8c8ef1c38cd388a765328`, and manifest digest
  `dffe2cd2e02dc280462556db25de854887e96ac1b23b62f513bdad6f1935c6da`.
  The parser reported only the known non-blocking EFM/iXBRL diagnostics.
- The run's overall terminal failure was separate: Debate `moderate-verdict`
  returned `failover_exhausted` after the LLM provider returned HTTP 502. The
  Fundamental report therefore did not render a completed artifact, and no
  desktop/mobile, keyboard, evidence-inspector, or same-snapshot valuation
  trace acceptance is claimed.

### Diagnostic result

**Incomplete and blocked.** The live workspace now proves the signed
identity-to-ingestion producer path and the Fundamental workflow reaches its
calculation boundary. The service-backed report cannot be accepted while the
default current filing is incompatible with the pinned validation runtime;
the service must select or provision a compatible verified filing/release under
the owning SEC boundary. Blocker #345 tracks this service-owned compatibility
gap. The independent Debate provider outage also prevents
the workspace run from reaching a completed terminal state. No acceptance
criterion is marked passed by this probe.

## Runtime restoration checkpoint

- After the temporary DQC 2026 compatibility probe, the isolated project
  `value-investment-agent-issue-325-fundamental` was recreated without
  removing its PostgreSQL named volume.
- The Fundamental service now uses the pinned DQC 2024 ruleset
  `/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip`
  with SHA-256
  `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930`.
  The taxonomy cache remains `us-gaap-2023-2024` with directory hash
  `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`.
- `docker compose -p value-investment-agent-issue-325-fundamental ... config
  --quiet` exited 0 before recreation. PostgreSQL and Fundamental service
  were healthy afterwards, and `GET http://127.0.0.1:18690/readyz` returned
  HTTP 200 with `{"status":"ready","contract_version":"internal.v1"}`.
- PostgreSQL retained `snapshot_manifests=8` and `canonical_facts=280`; no
  volume or repository data was deleted. This restores the documented pinned
  runtime but does not resolve #345 or mark any #325 acceptance criterion
  passed.

## Exact live service-backed run after #345 merge

- Date: 2026-11-07 (local). Code under test was the exact branch head
  `cc26190aa729bd9048a958b27fb6bcf4180f4f4c`, including merged #345
  compatibility changes. The dedicated project was
  `value-investment-agent-issue-325-fundamental`; its Fundamental service and
  PostgreSQL containers were healthy, and `GET http://127.0.0.1:18690/readyz`
  returned HTTP 200 `{"status":"ready","contract_version":"internal.v1"}`.
- The running Fundamental service configuration was inspected directly:
  organization allowlist included
  `org-sec-ingestion-test,43f50f0f-c6ff-4fb2-b4d2-ed366bc55613`, supported
  years were `2023,2024`, supported forms were `10-K`, the validation runtime
  was the pinned `us-gaap-2023-2024` bundle with DQC ruleset SHA-256
  `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930`, and
  the service cgroup limit was `1073741824` bytes (1 GiB).
- On the real `http://127.0.0.1:18681/workspace` route, a fresh run was
  `24ffeefc-6f67-4b62-9579-23e264d4a553` on thread
  `thread_1794057889777`. The operator selected
  `MSFT Microsoft Corporation NASDAQ` at 100% over `MSFT.TO` at 90%.
  Fundamental activity reached `calculate-valuation` and completed without an
  Agent-owned SEC fetch. The overall run later failed independently at Debate
  `moderate-verdict` with `failover_exhausted`; the LLM provider returned HTTP
  502 for the verdict path.
- The service log recorded signed identity resolution HTTP 200 followed by
  signed ingestion HTTP 422. A direct replay of the same producer-shaped
  request (correlation `issue325-diagnose-ingest-20261107-b`) returned the
  stable error `FACT_MAPPING_UNRESOLVED` / `requested mapping release is
  unavailable`. Read-only PostgreSQL inspection showed 7 mappings and the
  missing `sec-us-gaap-v1-filed_operating_evidence`; the existing mappings
  covered revenue, operating income, cash, debt, and diluted shares.
- Agent Core therefore correctly rendered `Report unavailable` and did not
  publish a snapshot-bound report artifact for this run. Database counts after
  the run were `sec_ingestion_acquisitions=6`, `snapshot_manifests=8`,
  `canonical_facts=280`, and `snapshot_facts=280`; no new snapshot was
  attributed to this failed request. No UI acceptance criterion is marked
  passed by this run.
- Commands and exit codes: `docker compose -p
  value-investment-agent-issue-325-fundamental ps` exit 0; `curl -fsS
  http://127.0.0.1:18690/readyz` exit 0; direct signed identity/ingestion
  replay exit 0 with the recorded HTTP 200/422 responses; browser route and
  activity inspection completed. Desktop/mobile viewport, keyboard evidence
  selection, evidence inspector, and same-snapshot valuation trace remain
  unverified. This is a diagnostic checkpoint, not `VERIFIED` acceptance.

### Diagnostic result

The pinned parser runtime and service boundary are healthy. The remaining
failure is a request-shape/fixture mismatch: the no-assumptions facts-only
path selects the transition model's additional `filed_operating_evidence`
field even though no valuation calculation is requested and the acceptance
mapping release does not contain that field. The next code checkpoint will
make facts-only ingestion use the base FCFF evidence set, then rerun the exact
workspace route and verify the service-owned snapshot and facts.

## Exact-head backend rebuild checkpoint

- Code under test: `715338b5e12421307e62599137189f34ac90fd32`.
- The isolated app Compose project was validated with
  `docker compose ... config --quiet` (exit 0) and only its `backend` service
  was rebuilt and recreated. The new backend image digest was
  `sha256:873799b4aa28f9a04678eb20ab897b5a041d9d1250347561e6eeb62414e24`.
- Existing app PostgreSQL, Redis, frontend, and LLM provider containers were
  retained. After recreation, `docker compose -p
  value-investment-agent-issue-325-app ps` reported all five app containers
  healthy and `curl -fsS http://127.0.0.1:18680/health` returned HTTP 200
  `{"status":"ok"}`. The backend runtime still had
  `FUNDAMENTAL_SERVICE_URL=http://host.docker.internal:18690` and the
  issue-scoped Fundamental service token configured.
- Commands: app Compose config exit 0; backend image build exit 0; backend
  recreation exit 0; Docker health and backend health curl exit 0. This
  checkpoint proves deployment of the producer fix; the workspace route and
  Fundamental snapshot acceptance were not run yet.

## Deadline-aligned live workspace run

- Date: 2026-11-07 (local). Code under test was the exact branch head
  `b806bc4c18f694ba69edc681bf3cdbffbbce28fb`, including the workflow deadline
  alignment with the Fundamental ingestion budget.
- Route: `http://127.0.0.1:18681/workspace`, Personal organization. The
  operator entered `MSFT` and selected `MSFT Microsoft Corporation NASDAQ` at
  100% match.
- Run: `098e6b16-e41b-43cb-b71a-882386abddf7`; thread
  `thread_1794059640677`. Fundamental identity resolution returned HTTP 200,
  and the producer ingestion request returned HTTP 200 with correlation ID
  `9451148ae2e34b769bec04bb9c5fb6e4`.
- The subsequent service snapshot-resolution request returned HTTP 422. The
  service recorded snapshot candidate
  `snapshot-364ba7b9bf9cdc402222764bb2d605d2` and manifest digest
  `144d2069533e31534249a71ac7a005472e656671b584b33cdcd535846b9b01f5`, but
  did not return a selectable snapshot-bound fact set to Agent Core. The UI
  therefore showed `Report unavailable` and did not fabricate a report.
- Fundamental PostgreSQL read-only counts after the run were 7 acquisition
  rows, 9 snapshot manifests, 388 canonical facts, and 388 snapshot-fact
  links. These counts do not establish that this failed resolution produced a
  new selectable snapshot.
- The overall workspace run separately failed in Debate because the LLM
  provider returned HTTP 502 and the workflow ended with `failover_exhausted`.
  This provider failure is independent of the Fundamental HTTP 422 and is not
  treated as a report acceptance result.
- Docker health remained green for the app and Fundamental projects; the
  Fundamental `/readyz` endpoint returned HTTP 200. The rebuilt Fundamental
  image was `sha256:1b2580dd6450471a8e09d3935f9778b0287dbd9fa99a7256f353695a975c8d1d`.
  Its configured runtime used years `2023,2024`, forms `10-K`, a 1 GiB memory
  limit, and DQC ruleset SHA-256
  `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930`.
- Result: **incomplete and blocked**. This run verifies the deadline-aligned
  producer reaches the service and that degraded report behavior is visible,
  but it does not verify a service-owned snapshot, matching fact IDs,
  valuation trace, manifest binding, desktop/mobile layout, keyboard
  operation, or evidence inspector. The exact HTTP 422 error payload must be
  replayed and traced in the Fundamental service before any UI acceptance.

## Current-head baseline checkpoint

- Date: 2026-11-07.
- Code under test: `e68b9f31` (`fix(#325): pin snapshot release profile in producer`),
  based on `origin/main` at `83fb733d9b23d51712ba30c41818e46e1fafa24b`.
- Agent focused checks: `uv run pytest tests/agents/fundamental/test_service_request_producer.py tests/agents/fundamental/test_fundamental_service_client.py tests/agents/fundamental/test_fundamental_service_cutover.py -q`
  exited 0 (`38 passed`).
- Frontend checks: `npm run lint` exited 0, `npm run typecheck` exited 0,
  and `npm run test -- --run` exited 0 (`52` files, `293` tests passed).
- Boundary checks: `python3 scripts/architecture_guard.py` exited 0 and
  `git diff --check` exited 0.
- Fundamental Compose project:
  `value-investment-agent-issue-325-fundamental`. PostgreSQL and Fundamental
  service were healthy; `curl -fsS http://127.0.0.1:18690/readyz` exited 0
  with `{"status":"ready","contract_version":"internal.v1"}`.
- This is a verification baseline only. No browser route, service-backed
  snapshot-to-valuation trace, desktop/mobile viewport, keyboard evidence
  selection, or evidence-inspector acceptance is claimed by this checkpoint.

## Allowlist-corrected live run and release-boundary diagnostic

- Date: 2026-11-07 (local). Code under test remained the exact head
  `c8582ce2f29347fc684eff78ccb75f19b41472e8`.
- The issue-scoped Fundamental service was recreated with the existing
  PostgreSQL and service-data volumes retained. Its ingestion organization
  allowlist was extended to include the disposable app organization
  `faeae7f6-bcc1-4927-886b-4234d1999d87`; no source or schema files were
  changed.
- Compose validation used the two current verification files with the pinned
  SEC runtime variables: `docker compose ... config --quiet` exited 0;
  `docker compose ... ps` exited 0 with both services healthy; and
  `curl -fsS http://127.0.0.1:18690/readyz` exited 0 with
  `{"status":"ready","contract_version":"internal.v1"}`. The service
  container image was `sha256:f302fb9f8029f898bf13f7ec6568d6fd434e1c629f05298c1e26182639b9e62c`.
- Route: `http://127.0.0.1:18881/workspace`, Personal organization, using the
  authenticated disposable account. The operator entered `MSFT` and selected
  `MSFT Microsoft Corporation NASDAQ` at 100% match over `MSFT.TO` at 90%.
  Run `bb1a5923-91e0-4daf-9f21-14055ba8ec14`; thread
  `thread_1794064175474`.
- Backend logs showed the cutover path without an Agent-owned SEC report fetch:
  signed identity resolution returned HTTP 200, and the SEC ingestion request
  returned HTTP 200 with correlation `5cafd9a55ae5429f81892c3d12a9fba0`.
  The subsequent signed snapshot resolution returned HTTP 409. A direct
  replay with correlation `issue325-snapshot-409-20261107` returned the exact
  error envelope `DATA_RELEASE_FACT_MISMATCH` / `selected canonical facts do
  not match the pinned data release`.
- Read-only PostgreSQL inspection identified the owning mismatch. Active
  profile `sec-public-pit-v1` points to release manifest
  `57e5404d38c7c7fe9cbf3157981a190dda75dc78baadb6af18e76ff9f813b149`, which
  declares `snapshot-364ba7b9bf9cdc402222764bb2d605d2` and its five fact
  digests. The run's ingestion created the newer
  `snapshot-40c8a9d248e4011b2649615245ab0fa9` with manifest digest
  `26f810ab7d006a9089b9984ec79031c51e5a327a6012f7dba43ba2e0ff33a437`.
  The service correctly refused to mix those newly selected canonical facts
  into the older immutable release. Counts after the run were 8 ingestion
  acquisitions, 10 snapshot manifests, 496 canonical facts, and 496
  snapshot-fact links.
- The Fundamental tab rendered `Report unavailable` with no artifact
  reference. The overall workflow then failed independently at
  `moderate-verdict` with `failover_exhausted` after the local LLM provider
  returned repeated HTTP 502 responses. The run therefore proves the
  allowlist correction and the service's fail-closed release boundary, but it
  does not verify a same-snapshot report, valuation trace, desktop/mobile
  layout, keyboard evidence selection, or evidence-inspector provenance.

### Diagnostic result

**Incomplete and blocked.** The prior 403 organization-policy mismatch is
resolved. The remaining 409 is the caller-time/release publication contract
tracked by blocker #347: a request that ingests data after the active immutable
release cannot resolve the newly created snapshot under that release. Do not
work around this by disabling release pinning, selecting unbound facts, or
falling back to an Agent-owned SEC report. The next step is to resolve #347's
caller-owned timestamp and release-compatible snapshot contract, then rerun
this exact workspace route before claiming #325 acceptance.

## Checkpoint: live artifact-save failure after snapshot boundary

- Date: 2026-11-08 (local). Code under test: `ddda9d8d` (`test(#325): keep snapshot fixture before request time`).
- Live route: `http://127.0.0.1:3000/workspace`; thread `thread_1794085200693`; run
  `c29b7e13-060c-4460-ab88-e61af9290560`.
- The Fundamental identity, snapshot, and facts endpoints all returned HTTP 200. The
  immutable snapshot timestamp contract also passed: facts returned the resolved
  `snapshot_timestamp`, which was earlier than the caller `valuation_timestamp`.
- The Fundamental subgraph checkpoint namespace
  `fundamental_agent:7279ff54-b2b4-6bcc-a9e5-f3878a31584b` reached checkpoint
  `00000000000000000000000000000005.0.6550448588202731`. Decoding its
  `fundamental_analysis` channel with `ormsgpack` showed
  `service_failure.code=ARTIFACT_SAVE_FAILED` and no `artifact` or
  `artifact_references` output.
- Source inspection identifies the owning wiring defect: `run_service_valuation_flow`
  invokes `runtime.save_financial_reports`, while production
  `FundamentalOrchestrator` no longer implements that method after the #327 legacy
  capability cleanup. The test-only `_Runtime` does implement it, so the existing
  cutover tests did not exercise production wiring. The resulting `AttributeError`
  is caught and reduced to `ARTIFACT_SAVE_FAILED`.
- The overall run still ended independently at Debate `moderate-verdict` with
  `failover_exhausted` after repeated LLM provider HTTP 502 responses. No
  `fundamental_service_facts` artifact was persisted, and the UI remained
  `Report unavailable`.

### Diagnostic result

**Incomplete and blocked.** The service boundary is now verified through facts
retrieval. The next owning-layer change is to restore Fundamental's artifact
persistence through the shared artifact storage port and add a production-wiring
regression test before rerunning the live route.

## Exact-head responsive UI checkpoint

- Date: 2026-11-08 (local). Code under test: `c0e2a5c6617204a114f06d4d6568b30c4b4605fa`
  (`fix(#325): constrain workspace report width`).
- The workspace report row now carries `min-w-0`. Before this change, the
  hidden desktop panels left the mobile grid row at 455.5px wide inside a
  390px viewport, which clipped report helper text, status alerts, and
  snapshot metadata at the page edge. The change lets the report panel inherit
  the viewport width; the facts table keeps its existing local horizontal
  scroll container for its five-column desktop shape.
- Static checks on the exact commit:

  | Command | Result |
  | --- | --- |
  | `npm run lint` in `frontend/` | exit 0 |
  | `npm run typecheck` in `frontend/` | exit 0 |
  | `npm run test -- --run src/features/workspace/workspace-page.test.tsx src/features/workspace/outputs/fundamental-analysis/FinancialTable.test.tsx src/features/workspace/outputs/fundamental-analysis/FundamentalAnalysisOutput.test.tsx` | exit 0; 3 files, 33 tests passed |
  | `git diff --check` | exit 0 |
  | frontend Docker production build | exit 0; image `sha256:a9b28f004985f28368996cf8b4511c15ddff1958908c716f632011ac465d4e6f` |
  | frontend container health | healthy |

- Live route: `http://127.0.0.1:3000/workspace?thread_id=thread_1794086274214&run_id=e2c1b17a-321c-41df-b5b5-6b2dedc0e7a2`.
  The service-backed Fundamental artifact remained
  `85bf2cb3-081b-4c5b-8a5f-c021017ec91d`, with snapshot
  `snapshot-82c9a009e0dd280f7d2e64d05b047262` and snapshot manifest
  `e54c631839298d340b1737bb661c7e0d05f7abef4a5e2bc17cf3acca42b9a698`.
- At viewport `390x844`, browser measurement reported
  `document.body.scrollWidth=390` and `document.documentElement.scrollWidth=390`.
  Report evidence and Fundamental service facts each occupied `x=16..374`
  (`358px`), and the valuation status alert also stayed within that range.
  The table's inner wrapper retained its intended `850px` content width and
  handled the extra columns with local horizontal scrolling; it did not widen
  the document. The screenshot showed wrapped report helper text, valuation
  explanation, snapshot/manifest metadata, fact IDs, and values without
  page-level clipping.
- At viewport `1440x900`, document and body scroll widths both equaled
  `1440px`; the Fundamental report, facts matrix, snapshot metadata, and
  valuation status were visible in the desktop panel.
- Keyboard acceptance: focusing `Inspect Revenue evidence` and pressing
  `Enter` opened the Evidence inspector. It displayed the source URL, period,
  confidence, fact ID, concept, accession, filed/available/captured timestamps,
  parser, taxonomy, source hash, snapshot ID, snapshot manifest digest, unit,
  and issue codes. Provenance fields absent from the artifact were rendered as
  `Unavailable` rather than inferred.

### Diagnostic result

The responsive report layout and keyboard evidence flow pass on the exact
frontend checkpoint. The overall workspace run still ended independently in
Debate with the known LLM provider `upstream_unavailable` / HTTP 502 failure;
that external failure is not a Fundamental report rendering failure. Issue
#325 remains incomplete until the remaining exact-head service/workflow
acceptance and release gates are rerun and recorded.

## Exact-head final verification gate

- The documentation checkpoint `ee27111f` was verified with the frontend code
  at `c0e2a5c6`; the documentation-only commit did not change runtime code.
- Exact-head commands and results:

  | Command | Result |
  | --- | --- |
  | `npm run lint` in `frontend/` | exit 0 |
  | `npm run typecheck` in `frontend/` | exit 0 |
  | `npm run test -- --run` in `frontend/` | exit 0; 52 files, 293 tests passed |
  | `uv run --project finance-agent-core pytest finance-agent-core/tests/agents/fundamental/test_fundamental_service_client.py finance-agent-core/tests/agents/fundamental/test_fundamental_service_cutover.py -q` | exit 0; 33 passed |
  | `python3 scripts/architecture_guard.py` | exit 0 |
  | `git diff --check` | exit 0 |

- Docker health: all five app containers and both Fundamental containers were
  healthy. `curl -fsS http://127.0.0.1:8000/health` returned HTTP 200
  `{"status":"ok"}`. The current Fundamental Compose mapping is
  `127.0.0.1:18080->8080`; `curl -fsS http://127.0.0.1:18080/readyz` returned
  HTTP 200 `{"status":"ready","contract_version":"internal.v1"}` and the
  service image was
  `sha256:cb18e009a29b09ff1fb4a294357b7dc451ec54e2ec583562ed7373d54cc99e6a`.
  A probe of the historical `18690` port exited 7 because that port is not
  mapped by the current project; it did not indicate a container health
  failure.
- No pull request or CI result exists yet. The branch remains unmerged and the
  issue remains open; these checks do not mark #325 `VERIFIED` or close it.

## Exact-head semantic UI and focus acceptance

- Date: 2026-11-08 (local). Code under test: `dfddf265` (`fix(#325): restore
  evidence focus on mobile close`). This exact head includes the responsive
  width fix, semantic facts-table states, mobile evidence-sheet selection, and
  focus restoration.
- Full exact-head checks:

  | Command | Result |
  | --- | --- |
  | `npm run lint` in `frontend/` | exit 0 |
  | `npm run typecheck` in `frontend/` | exit 0 |
  | `npm run test -- --run` in `frontend/` | exit 0; 52 files, 296 tests passed |
  | `uv run --project finance-agent-core pytest finance-agent-core/tests/agents/fundamental/test_fundamental_service_client.py finance-agent-core/tests/agents/fundamental/test_fundamental_service_cutover.py -q` | exit 0; 33 passed |
  | `python3 scripts/architecture_guard.py` | exit 0 |
  | `git diff --check` | exit 0 |
  | frontend Docker production build | exit 0; image `sha256:4c2652a2a0f0954892f4309dd3f544c9908c4da220e8f8f2c00f5be9b5afb2ac` |
  | frontend container health | healthy |

- The live route remained
  `http://127.0.0.1:3000/workspace?thread_id=thread_1794086274214&run_id=e2c1b17a-321c-41df-b5b5-6b2dedc0e7a2`, with artifact
  `85bf2cb3-081b-4c5b-8a5f-c021017ec91d`, snapshot
  `snapshot-82c9a009e0dd280f7d2e64d05b047262`, and snapshot manifest
  `e54c631839298d340b1737bb661c7e0d05f7abef4a5e2bc17cf3acca42b9a698`.
- At `390x844`, DOM measurement returned
  `innerWidth=390`, `document.body.scrollWidth=390`,
  `document.documentElement.scrollWidth=390`, workspace report row width
  `390px`, and report-evidence width `358px` at `x=16`. The facts table exposed
  a meaningful caption, five `scope="col"` headers, and five text-labelled
  quality badges. The wide facts content remained inside its local horizontal
  scroll container.
- Keyboard flow at `390x844`: pressing `Enter` on `Inspect Revenue evidence`
  opened the mobile Evidence inspector. The inspector showed the source URL,
  period, confidence, fact ID, concept, accession, filed/available/captured
  timestamps, parser, taxonomy, source hash, snapshot, manifest, unit, and
  issue codes. Missing taxonomy-manifest and mapping provenance remained
  explicitly `Unavailable`. Closing the Sheet restored focus to the original
  `Inspect Revenue evidence` button immediately and after settling.
- At `1440x900`, body/document scroll widths both equaled `1440px`, the
  persistent desktop Evidence inspector was present, and the same table
  caption/header semantics were exposed. The report remained bounded within
  the center panel.

### Current status

The report display, responsive layout, semantic table states, mobile evidence
selection, keyboard close behavior, and focus restoration now pass on the exact
branch head. #325 is still **incomplete and blocked** for delivery: no PR or
PR-CI result exists, the issue remains OPEN with its `blocker` label, and the
overall workspace run still has the independent Debate LLM provider
`upstream_unavailable` / HTTP 502 failure recorded above. Do not mark the issue
`VERIFIED` or close it until the required service/workflow acceptance is
rerun on the delivery PR and the external provider gate is resolved or
explicitly accepted by the owning issue.
