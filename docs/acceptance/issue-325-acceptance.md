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
required before the MSFT service-backed acceptance can proceed.
