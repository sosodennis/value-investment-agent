# Issue 361 replay checkpoint, 2026-11-10

This checkpoint records a blocked preflight. It is not full replay acceptance and does not mark any valuation `verified`.

## Issue and commit

- #361 is OPEN and remains the only active issue in this workstream. Its GitHub body now reflects that #351 through #355 are CLOSED and #352's composer is merged by PR #363.
- Blocker #369 is OPEN and labeled `blocker` and `fundamental-service`. It tracks point-in-time market-policy evidence that the #352 composer needs for the 2016 decision dates.
- Worktree: `/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-replay-evidence`.
- Branch: `codex/issue-361-replay-evidence`.
- The merged `origin/main` base is `485b2f59742454151faf56730e1e421e850cf978`; merge commit `a20cb0ef9b9536de44f8eb53f628a3fe8d092418` retains prior #361 commits.
- The preflight assessment commit is `292ab9d9fe03e296c0ce9ee60c1054fd031062a6`. Artifact writer commit `21f16617355f663bdaa38c7617f03c33b37619d4` stores those canonical outputs as deterministic gzip. The current report pins Python `3.11.15`, Pydantic `2.14.2`, and Fundamental Service lock SHA-256 `57b9ea3f92002720d4bce735df3316df071479da4c0599a31ae914e9e6c32a18`.

## Preflight evidence

The command below ran on implementation commit `292ab9d9fe03e296c0ce9ee60c1054fd031062a6`:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service python -m fundamental_service.history_replay
```

It exited 0 and returned status `underpowered` with replay status `preflight_blocked_before_service_composer`. The fixed cohort contains 100 issuers. The evidence contains 91 first subsequent original annual filings and 87 issuers with raw candidate label facts, but zero reviewed full-model mappings and zero eligible model labels. The listed candidates are not approved issuer-period mappings.

Both `fcff_dcf` and `transition_fcff_dcf` have forecast coverage `0/100`, independent issuer count `0`, and no forecast error measurement. Each records 100 missing cases for full-model field mapping, release-bound canonical facts, and admissible historical market policy. The report recommends abstention for all 100 issuers per model. `supported_history_threshold` remains `null` and the overall evidence status is `underpowered`.

The canonical input digest is `be0c2a6fff469b4d00858a1107d39cc252f0cd42d24c903e8260aae111e5a9ff`. The report digest is `d4777dca602548146fb556ebc73d356defbcbda36e54ca8dbf96779aa4f11f45`. Other artifact digests are mapping `b6c383965a4ca4327e7e164f9501288afb514cf93a45ab6be087a227ff6555f8`, forecast output `73d51d9dbf1f60323443af78d9a0c80a77037a18a2aba5621086428ccfefc589`, and label output `05b7b532b996f05a6733775f1b84df300d96d964bb5ad9fe2d1d397000367b7a`.

The checkpoint hook rejected raw JSON artifacts because it appends a newline and the label output is 567 KB. The files are now stored as `.json.gz` copies. Each filename still uses the SHA-256 of its decompressed canonical JSON. The archive check confirmed that all five decompressed hashes match their filenames. The label output compresses to 60 KB. The replay writer uses gzip with `mtime=0` and keeps temporary-file plus atomic-rename writes.

The same command ran again with the same commit, manifests, and runtime pins. It exited 0, returned the same input and report digests, and reported `wrote=false` for all five artifacts. This proves preflight artifact idempotency only. It is not a second full composer replay.

## Artifact writer rerun on the exact commit

The revised writer ran twice on commit `21f16617355f663bdaa38c7617f03c33b37619d4` with the same manifests and runtime pins:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service python -m fundamental_service.history_replay
```

Both commands exited 0. The first run wrote the new input and report artifacts and reused the mapping, forecast, and label artifacts. The second run reported `wrote=false` for all five. Both runs returned input digest `e845930d296eed509bd6d40a185f462ec50ff67437419fc7d1ea2d398bc27a5b` and report digest `e298ab873bb96a44a8d8e916a8aeb1f7d110dd335b2f2fac79e2a84bf5085de0`. The mapping, forecast, and label digests remain `b6c383965a4ca4327e7e164f9501288afb514cf93a45ab6be087a227ff6555f8`, `73d51d9dbf1f60323443af78d9a0c80a77037a18a2aba5621086428ccfefc589`, and `05b7b532b996f05a6733775f1b84df300d96d964bb5ad9fe2d1d397000367b7a`.

The report records the exact implementation commit, status `underpowered`, 0/100 forecasts for both models, zero composer invocations, and `supported_history_threshold: null`. The second run proves deterministic preflight artifact reuse. It is not a full composer replay.

## Current exact-head preflight rerun

The existing #361 head `29c82dbb790ce82d3b163789a84f35a359ad9a79` was replayed twice with the same fixed cohort, evidence manifest, mapping report, and runtime pins:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service python -m fundamental_service.history_replay
```

Both runs exited 0 and returned input digest `c34eb1b1d3d22c8d8ef92952446309d9cdcc18201336d4f13385c168055aa0d9` and report digest `5e405346e18919baee62c9e6303d612525ef663e99d26a0bae520bc6a694dfbd`. The mapping, forecast, and label digests remained `b6c383965a4ca4327e7e164f9501288afb514cf93a45ab6be087a227ff6555f8`, `73d51d9dbf1f60323443af78d9a0c80a77037a18a2aba5621086428ccfefc589`, and `05b7b532b996f05a6733775f1b84df300d96d964bb5ad9fe2d1d397000367b7a`. The first run wrote only the new input and report artifacts; the second reported `wrote=false` for all five artifacts.

The report still retains all 100 fixed issuers, has `status: underpowered`, reports zero composer invocations and `0/100` forecast coverage for both models, and keeps `supported_history_threshold: null`. Focused mapping and replay tests passed on this exact head: `9 passed`. This rerun confirms preflight determinism and artifact reuse only; it does not satisfy forecast, label, or full replay acceptance.

## Service boundary check

The isolated Docker project is `value-investment-agent-361-replay-evidence`, using `compose/verification/docker-compose.issue280-operations.yml`. Compose configuration passed with service port `18661` and Postgres port `18662`. Its network is `value-investment-agent-361-replay-evidence_default`; its volumes are `value-investment-agent-361-replay-evidence_fundamental-postgres-data` and `value-investment-agent-361-replay-evidence_fundamental-service-data`.

Both `fundamental-service` and `fundamental-postgres` were healthy. `GET http://127.0.0.1:18661/readyz` returned `ready`, with `identity_resolution_configured=false`. The database contained zero snapshots and zero data releases.

A valid signed internal request reached `POST /v1/valuation/prepare` with model `fcff_dcf`, a deliberately absent snapshot ID `issue-361-unavailable-snapshot`, and a well-formed zero digest. The service returned HTTP 404 `SNAPSHOT_NOT_FOUND`. This confirms that the isolated stack has no release-bound input for the replay. It does not establish forecast behavior for a valid historical release.

The composer policy evidence in the preflight is `fcff-market-policy-2025-v1`, available at `2025-01-03T00:00:00Z`. That policy is not admissible at any fixed 2016 decision date. The integration test for `/v1/valuation/prepare` confirms that the composer attaches this 2025 evidence timestamp. No policy values were backdated or supplied around the composer. Blocker #369 records the service-owned resolution.

## Draft PR and CI status

Draft PR [#370](https://github.com/sosodennis/value-investment-agent/pull/370) targets `main`, references #361 without a closing keyword, and at this checkpoint points to commit `d3ee1d7a04362171c5215e9365151d556a9493e8`. Its merge state was `CLEAN`, it had no review decision, and it remained a draft. GitHub Actions run `42770796965` completed successfully: 11 checks passed (`backend-lint-test`, `contract-codegen-check`, `contract-policy`, `frontend-lint-type-test`, `fundamental-offline-fixture-contracts`, `llm-provider-contract-gate`, `llm-provider-service-contract-gate`, `model-inference-service-contract-gate`, `notification-postgres-integration`, `production-compose-secret-contract`, and `search-service-contract-gate`). `fundamental-release-gate` was skipped, so CI does not establish release-backed replay acceptance.

The isolated #361 Compose project is still running with healthy `fundamental-service` and `fundamental-postgres` containers on ports `18661` and `18662`. The prior readiness and database evidence remains unchanged: identity resolution is not configured, and the database has no snapshots or data releases. This is not service-backed replay acceptance.

## Verification and remaining work

On implementation commit `292ab9d9fe03e296c0ce9ee60c1054fd031062a6`, 38 focused tests passed, the architecture guard passed, Ruff and format checks passed, mypy passed for the new module and tests, and the staged diff check passed.

The artifact writer update passed 9 focused tests:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_mapping_audit.py fundamental-service/tests/test_history_replay.py -q
```

The writer checks also passed:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core --group dev ruff check fundamental-service/src/fundamental_service/history_replay.py fundamental-service/tests/test_history_replay.py
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core --group dev ruff format --check fundamental-service/src/fundamental_service/history_replay.py fundamental-service/tests/test_history_replay.py
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core --group dev --with mypy==1.18.2 mypy --follow-imports=silent --ignore-missing-imports fundamental-service/src/fundamental_service/history_replay.py fundamental-service/tests/test_history_replay.py
python3 scripts/architecture_guard.py
git diff --check
```

All six commands exited 0. A broader mypy run without `--follow-imports=silent` reported 95 errors in unchanged imported files `contracts.py`, `policies.py`, and `snapshots.py`. The changed module and test had no reported errors in that run. The focused mypy command above passed.

On checkpoint commit `d3ee1d7a04362171c5215e9365151d556a9493e8`, focused mapping and replay tests passed (`9 passed`); Ruff, format, focused mypy, architecture guard, and diff checks also passed. The preflight ran twice on its exact replay commit `29c82dbb790ce82d3b163789a84f35a359ad9a79` with identical input/report digests; the second run reused all five artifacts. The full mapping, history replay, forecast, label, deterministic full replay, failure-retention, and release-backed service acceptance gates remain NOT VERIFIED. PR #370's 11 passing contract and lint checks do not substitute for its skipped release gate or service-backed replay. Resolve #369, review issuer- and period-aware full-model mappings, create immutable point-in-time releases, then run both models through the #352 composer and repeat the full replay before deciding whether the threshold remains null.

## Full-model input preparation checkpoint

The resumed base is `1aa6989d68d03afbcd933a2cae437388d7502c71`. Fetch and an ordinary `git merge --no-edit origin/main` returned `Already up to date`; the branch retains all WIP checkpoints. Draft PR #370 already exists. #361 remains the delivery issue.

The new `fundamental_service.history_replay_inputs` module captures one immutable SEC Company Facts bundle per CIK, decision accession, valuation timestamp, and versioned source profile. A bundle stores the original response bytes together with its receipt in one atomic write. A resumed capture reuses those bundles, including failures, without requesting the source again. It then creates a canonical, content-addressed source manifest and a full-model issuer-period mapping review package. The review package uses the existing service requirements and filing chronology. It retains unit and period rejections, conflicting candidates, amendments, first-subsequent original labels, and missing fields. No candidate becomes an approved mapping or canonical fact. Company Facts omits original XBRL fact and context IDs; this limitation is explicit instead of manufacturing those identifiers.

Before the implementation checkpoint, this command passed 56 tests:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_mapping_audit.py fundamental-service/tests/test_history_replay.py fundamental-service/tests/test_history_replay_inputs.py fundamental-service/tests/test_history_cohort.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_annual_history.py fundamental-service/tests/test_valuation_requirements.py fundamental-service/tests/test_valuation_preparation.py fundamental-service/tests/test_valuation_preparation_integration.py fundamental-service/tests/test_data_release_attestations.py -q
```

Ruff, format, focused mypy on the new module and tests, `python3 scripts/architecture_guard.py`, and `git diff --check` exited 0. This was a working-tree check on the resumed base; exact-commit checks follow the checkpoint. No full composer replay or service acceptance is claimed. Next, capture all 100 fixed sources, generate and repeat the review package, and record its exact input/output digests and per-field gaps. Independent mapping review and admissible historical policy remain required before release-backed forecasting.

## Complete Company Facts capture and review storage

The capture on exact commit `99f58fa6c7dec33f17d909a94354bfb35feb659f` returned exit 0 with 100 selected issuers, 100 captured issuers, and 100 requests. Its initial source-manifest digest was `039b419c963aee863a93895848ba39417b6cd48e306fd085e1fc339d834ac504`. It used only the fixed cohort CIKs and did not replace any issuer. The configured SEC contact was read from the primary worktree's ignored `.env` without recording its value.

The initial base64 bundle format exceeded the 500 KB Git hook for some issuers. The revised bundle stores a canonical receipt, a newline delimiter, and the exact original response bytes in one deterministic gzip file. The original capture is preserved at `/tmp/issue361-capture-99f58fa6-original`; the committed replacement encoding is under `issue-361-full-model-inputs-v1/source_index/`. All 100 original response byte comparisons passed. Conversion made zero network requests. The largest new bundle is 378580 bytes. A mapping package is written as 100 issuer artifacts and one digest manifest, so no evidence is truncated to pass the file-size gate.

The review package includes every released model role, candidate concept rules, original and amendment accessions, the first subsequent original filing, rejected units and durations, conflicting values, point-in-time cover shares, source hashes, mapping version, model versions, full service policy evidence, and runtime pins. Missing candidates remain missing. None of these candidate rules is a canonical mapping approval. Original XBRL fact/context IDs still require filing-instance evidence and are explicitly unavailable in Company Facts. No data release is fabricated.

Working-tree validation after the storage and point-in-time changes passed 58 focused tests using the command above. Ruff, focused mypy, architecture guard, and the diff check passed. The next exact-commit run must regenerate the source manifest without another SEC request, create the mapping review package twice, compare every digest and byte, then record the remaining release and historical-policy gates. Full replay remains NOT VERIFIED.

## Exact input-preparation verification

On exact implementation commit `f9b18a5d850ceb6430935a2ee8a0cd9c3c1f4203`, source capture and mapping review preparation each ran twice with exit 0. Both capture runs downloaded zero responses and reused the 100 immutable source bundles. The source manifest digest is `83909f9be4368fe1453d7707902b8b70009dfe62727e27db4c27f94b1f9cc020`. The mapping review manifest digest is `8b8513870f02c9522c52d4e1ac20ba93c551bb79fe3045eab956249d63cfd602`. Every second-run artifact reported `wrote=false`, including all 100 issuer review files. Decompressed digest verification passed for all 102 generated artifacts. `issue-361-full-model-inputs-v1/idempotency-evidence.json` records the commands, results, and command-output hashes.

The exact implementation passed 58 focused tests, Ruff, formatting, focused mypy, architecture guard, and diff checks. All 100 issuers remain in the denominator. Revenue has at least one raw history candidate for 75 issuers and at least one raw label candidate for 66; these are candidate inventories, not reviewed coverage or sufficient-history counts. Several fields have no candidate mapping and remain explicit gaps. No forecast error has been measured and no full composer replay has run. The threshold remains null.

Next: resolve the service-owned historical evidence selection and prepare concrete issuer-period mapping decisions for independent review, then create legitimate releases and execute the formal composer replay. Mapping approval must satisfy `MappingReviewEvidenceV1` (distinct author/reviewer and signed evidence); the preparation package does not supply that approval.

## Historical market evidence and policy-selection implementation

The working tree based on `02ecd78d` adds a source-capture command for ALFRED DGS10 vintages on the day before each fixed decision date. All 100 issuer decisions bind to the unchanged SEC input manifest; 35 shared vintages avoid duplicate requests. Original source bytes, vintage headers, percent units, observation dates, conservative availability, capture time, source digests and frozen failures are retained. Risk-free observations are unapproved candidates. Beta, equity risk premium, debt cost, debt/equity weights and terminal growth remain explicitly unresolved. These macro observations are not threshold ground truth.

The service-owned policy registry now selects the unique most recent effective release whose market evidence was available at the valuation timestamp. Explicit pins cannot bypass future evidence. Same-effective ambiguity still fails. A policy with market inputs must bind those inputs in its digest; the legacy digest cannot leave them unsigned by content. The 2025 policy and all valuation formulas remain unchanged. Design and integrity evidence are linked in blocker #369 comments.

Working-tree validation: the entire Fundamental Service suite returned `337 passed, 25 skipped` (exit 0). Skips include external/PostgreSQL gates and do not establish service acceptance. Ruff/format, focused mypy on the new capture module and tests, architecture guard, and diff checks passed. Next checkpoint must capture real sources on its exact SHA, repeat with downloads=0/wrote=false, verify candidate provenance, and execute the isolated PostgreSQL/service gates. Independent mapping review and historical policy approval remain open; no signed approval is manufactured.

## Complete historical proxy-policy proposal

The exact `19797ff0ab8f87e22b945202f62d16bcae504a6b` macro capture made 35 requests, retained all 100 decisions, and parsed 35 valid ALFRED vintages. Its input digest is `83909f9be4368fe1453d7707902b8b70009dfe62727e27db4c27f94b1f9cc020`; output digest is `2c17fd3e0a6022e70ab07e92241ec010541480d6c99662bd3fb9394e80979580`. The second execution exited 0 with downloads=0 and wrote=false. All candidate availability timestamps precede their fixed decision dates. The complete service suite on that exact SHA returned 337 passed/25 skipped.

Direct publisher evidence now supports a complete review proposal: Damodaran's archived January 2015 US WACC workbook (updated 2015-01-05) supplies total-market beta, ERP, debt cost and debt/equity weights. The archive's publication-month label is conservatively available from 2015-02-01. The dated 2012-01-25 FOMC statement supplies a proposed 2% inflation-based terminal-growth proxy, conservatively available 2012-01-26. These are explicit uniform policy proxies, not observed issuer parameters. Original responses and capture receipts are frozen in `issue-361-market-evidence-v1/reference_sources/`. The currently revised historical-premium workbook was excluded. No current issuer membership, analyst estimate or target is used as ground truth.

`history_policy_proposal.py` parses the exact workbook row/cells with xlrd 2.0.2 and retains the source hash, transformation, source dates, terms, proxy meaning and proposal version. All seven roles are available for review for all 100 decisions. Approval remains null; the command cannot publish or activate a policy. This resolves source discovery and prepares a concrete review result; it does not supply independent approval.

The isolated Docker project was rebuilt from `19797ff0` using the operations file plus SEC ingestion overlay and an issue-owned ignored `.env` (SHA-256 `610964e8e6b3f8bdd8d1cfcbc022a2fded6f0cc67fe88c579018782371996c3e`). Service/Postgres ports remain 18661/18662. Readiness now reports identity_resolution_configured=true. All 45 image Python source hashes matched that implementation. Existing taxonomy assets certify 2023/2024 only; identity readiness does not establish 2016 filing compatibility or release-backed replay. No other project's resources were modified.

The PostgreSQL suite initially returned 15 passed/2 failed because its fake acquisition settings lacked supported_filing_years/forms. Adding those two fixture fields returned 17 passed. The working tree with the proposal returned 340 passed/25 skipped for the full service suite. New-module focused mypy passed. Whole-file policies.py mypy still reports 83 pre-existing diagnostics versus 86 at base `02ecd78d`; normalized comparison found zero new diagnostics and three resolved diagnostics. This is not a claim that the whole module passes mypy. Full replay, signed mapping review, historical policy approval and historical regulatory validation remain open gates.

## Exact proposal and service evidence

Implementation commit `f7ff60b0647c247a12c1bacb819c8ee027ac82fe` generated the complete proposal twice. Both commands exited 0 with input digest `8f552ffcf9c2f3c213cc2beb70a2e25a3cca23a5bf3434b3a412d6def9b0c9e3` and output digest `97f2f7ddd4100cd990d3cb5197f3a8c94f46a349383ef535c7e4dfc60a88604b`; the second returned wrote=false. The full offline suite returned 340 passed/25 skipped, PostgreSQL returned 17 passed, new-module focused mypy passed, and Ruff/architecture guard passed on this exact implementation. Docker was rebuilt and all 46 image Python files matched the checkout. SEC identity readiness is true. `issue-361-service-runtime.json` records the exact image, source-tree digest, isolated project, env digest, ports, resources and limitations.

The human-readable `issue-361-review-handoff.md` identifies the dated seven-role proposal, its proxy meanings, fixed mapping packets, retained missingness, independent-signature contract and remaining scientific/runtime gates. #361 is not complete; no formal composer replay is asserted. The existing branch and worktree remain required, and the issue-owned Compose project is retained while acceptance is incomplete.

## Authored issuer-period mapping proposals

The frozen 100 issuer review packets now feed `history_mapping_proposals.py`, which authors explicit per-accession/period/role decisions. The working-tree result contains 19,437 decisions: 5,052 unique exact-candidate proposals, 1,589 unresolved competing candidates and 12,796 missing eligible candidates. A unique numerical candidate is not semantic approval. Each preview remains provisional, with reviewer/signature null and explicit disclosure/scope/sign/era checks. All competing IDs, rejected candidates, missing reasons and source facts remain traceable through their immutable issuer input digest. No canonical facts or releases are published.

Six new mapping-proposal tests cover unique candidates, value/concept ambiguity, retained missingness, source integrity, all 100 issuer identities, unchanged artifact reruns and altered issuer evidence. Focused mapping/input/preflight tests returned 22 passed; new module/test mypy, Ruff and architecture guard passed. The next exact checkpoint must generate the per-issuer proposals twice and record all artifact digests and wrote=false results.

CI on metadata checkpoint `8564745d` completed with 11 successful checks in GitHub Actions run `42791115585`; fundamental-release-gate was skipped. Draft PR #370 remains open. This CI result does not verify the subsequent working-tree mapping-proposal implementation.

## Mapping rerun and command provenance gate

On exact `5ef6d07fa10134d9248f50c05bc478d51b32a0fb`, mapping proposal generation and its confirmed subsequent rerun exited 0 with input `8b8513870f02c9522c52d4e1ac20ba93c551bb79fe3045eab956249d63cfd602` and output `760ba098cdac8aa52b07bdb8e51a564adf7056ce13fb14d2b46eb0c84fd5011d`. The confirmed rerun reused all 100 issuer files plus the manifest, with wrote=false; all decompressed hashes match. The full service suite on that exact SHA returned 346 passed/25 skipped.

Review found that new command entrypoints resolved HEAD but did not yet reject dirty source. All preparation CLIs now require clean tracked source/inputs and require their own entrypoint to be Git-tracked before any source I/O. Five command-boundary tests exercise early rejection and untracked-source rejection. This strengthens the exact-commit evidence claim without altering the proposal or valuation rules. Working-tree focused preparation/provenance tests returned 36 passed; six-module focused mypy, Ruff and architecture guard passed. Next: checkpoint this guard, rerun preparation under the clean-source gate, preserve its immutable outputs, and keep the signed-review/release/full-replay gates open.

## Project signing implementation

The user authorized project signing and explicitly requested a script if no signer existed. The project had no configured reviewer private key; its only committed trust root is a development fixture. The new `fundamental-history-review-sign` CLI creates and reuses an issue-owned Ed25519 key in ignored storage, seals current proposals as explicitly unapproved, signs completed independent mapping reviews through the existing release schema, and verifies against a separately pinned public identity. It does not edit mappings, activate releases or change deployment trust roots. The signing instructions are in `fundamental-service/docs/issue361-project-signing.md`.

This change builds on exact clean-source implementation `3b8964f371326e116292f80181bba91c71085bf7`, whose full offline suite passed 351 tests with 25 skipped. New signing/release/provenance tests passed 20 tests; focused mypy, Ruff/format, architecture guard and diff check passed (all exit 0). Tests use temporary synthetic keys and cannot approve production mappings. After this implementation is committed, initialize the real project key, seal both canonical proposals twice, verify the public signatures/subject digests and record unchanged writes on that exact SHA. Complete composer replay remains unverified; supported thresholds remain null.

A read-only historical-parser diagnostic on `3b8964f3` used the correct original `acug-20150930.xml` entrypoint. Pinned Arelle 2.47.4 in offline parse-only mode returned 327 facts, no findings and zero network attempts. Source XML SHA-256: `fc13b856abb859aab0c3e23deb20c1801054d9742ee7f7c8f1acf92c9e7040d1`. Taxonomy-cache digest: `9d3b620dea156fbe37d7cb08da453aa2cec168b926851e2d50a7dcb7c25bed29`. Output remains `/tmp/issue361-historical-parse-diagnostic.log`; this diagnostic is not committed regulatory acceptance, does not run EFM/DQC and does not certify all cohort filings. The earlier wrong-HTML-entrypoint diagnostic is not evidence of unsupported XML parsing.

## Exact project signatures and release-bound runner

On exact signing implementation `dc34aa0846f66378de7d876b9d40047850e4113c`, initialized the project signer `value-investment-agent/issue-361-project-signer`. The public identity digest is `e541afcf1d21bb4afa58e56a6db3b222688c9ec89dfe590b54d9d11772556047`; its private key is mode 0600 in ignored `.audit/issue-361-signing/project-signer.pem` and is not committed. Initialization rerun returned key_wrote=false/identity wrote=false. No production trust roots were changed.

The exact mapping proposal `760ba098cdac8aa52b07bdb8e51a564adf7056ce13fb14d2b46eb0c84fd5011d` produced seal `f2b81ec096309842457df27879e1377f58f6daa87e0ff87b05312c5cdc560651`. Historical policy proposal `97f2f7ddd4100cd990d3cb5197f3a8c94f46a349383ef535c7e4dfc60a88604b` produced seal `0de95c472620d6510a0980bf3e4f6078070e9ec04f60ca0796aabf50a06829d8`. Both commands ran twice sequentially (all exit 0); both second runs returned the same digest and wrote=false. Verification against the pinned public identity and original subject returned verified=true for both. `issue-361-signatures-v1/idempotency-evidence.json` records exact commands, input/output digests, runtime pins, exit results and output hashes. These are explicitly unapproved package seals, not signed canonical mapping approvals. The full offline suite on the signing implementation returned 362 passed/25 skipped.

The subsequent working tree adds the service-owned callable release-bound runner documented in `fundamental-service/docs/issue361-replay-runner.md`. Real application/composer/calculator fixtures now exercise forecast generation, first-original revenue/FCFF labels and persisted calculation artifacts. It retains missing releases, incomplete labels, amendment exclusions, both model dispositions and service failures; rejects changed cohort/policy/mapping/snapshot pins; normalizes chronology; and reads labels only after all forecasts finish. Historical FCFF label arithmetic stays in the existing historical-metric owner with source fact lineage; forecast values come directly from calculator nodes. No approved numerical threshold or quality promotion is introduced.

The 12 runner tests passed, including a second replay with identical canonical output and no additional calculation/report artifacts. Earlier combined runner/preparation tests passed 23 tests before the fixed-cohort/score addition. These are synthetic engineering tests, not the fixed 100-issuer full replay. Next: exact-commit suite/lint/type/architecture checks, rebuild the isolated image, push the preserved checkpoints and refresh PR #370. Historical signed mapping approval, policy approval, regulatory validation, actual canonical releases and full cohort replay remain open.

The production runner CLI now requires the exact runtime pins and fixed calibration cohort before starting the existing production composition; it offers no fixture fallback. The final focused runner suite passed 13 tests, including CLI rejection of engineering plans and changed runtime. Focused mypy on runner/CLI/tests passed. The full working-tree Fundamental suite before the additional CLI test returned 374 passed/25 skipped. Whole `valuation_preparation.py` mypy comparison to `dc34aa08` reports 181 baseline diagnostics and 181 current diagnostics, zero new normalized diagnostics; this is not a passing whole-module type check. Full type acceptance remains open alongside the existing policies baseline. No new diagnostic is accepted in changed code.

## Composer mapping lineage correction

Exact runner checkpoint `5c612858` passed the full service suite: 375 passed/25 skipped, exit 0. Subsequent review found the application always inherited the low-level composer's default mapping version. The owning use case now checks the pinned release's canonical mapping digests/approval, source concept/normalized-field match and fact decision IDs, requires a coherent version and forwards it into the existing composer. Production missing mapping metadata fails explicitly; the existing nonproduction fixture path is unchanged. No valuation formula is changed.

Focused real-application runner/integration tests returned 18 passed. New cases reject changed mapping metadata, unbound facts and missing mapping records, and validate a non-default reviewed version. The CLI prints report statistics with canonical Decimal serialization. The runner/CLI/test type checks pass after a fixture annotation; full application type comparison remains 11 baseline diagnostics versus 11 current, with zero new normalized diagnostics. Full valuation-preparation comparison remains 181/181 with none new. Whole-module type acceptance remains open; no passing full type result is asserted.

Next: commit these corrections, rerun affected exact-commit verification, rebuild/check only the issue-owned Compose image, push all preserved checkpoints, and update PR #370/CI. Scientific acceptance still requires actual independent mapping review, historical policy approval, regulatory validation and the real fixed-cohort composer replay; project signatures authenticate the proposal but do not replace those gates.

## Exact composer-binding verification

Exact implementation `21bc5210b4a0b4cc7dbc07e94dd35bd64c0f9ec5` passed 379 offline tests/25 skipped, 17 isolated PostgreSQL tests, focused mypy on five runner/signing source/test files, architecture guard and git diff --check (all exit 0). Both committed proposal seals verified against their original subjects on this exact SHA. Full service Ruff lint passed. Whole-tree Ruff formatting found one pre-existing failure in unchanged `tests/test_release_runner.py`; copying that file from origin/main and running the same formatter reproduced the failure. Changed-file formatting passes; no unrelated formatting rewrite is included.

The isolated image built successfully from `21bc5210`. Because the newly initialized private key resides in ignored `.audit/`, add that issue signing directory to the Docker context exclusions before the final acceptance rebuild. The Dockerfile only copies explicit source paths, but the key should not enter the build context. This does not rotate or publish the key. Next: commit the exclusion, rebuild/start the same isolated project and record image-source equality/readiness, then refresh PR and CI. Full replay remains unverified.

## Isolated runtime and CI after project signing

Build/runtime checkpoint `3d195443118bd5708d50e6a2a2fb43ac60dc104d` rebuilt and restarted only `value-investment-agent-361-replay-evidence` using its existing `.env` and ordered operations/SEC overlays. Build and start exited 0. Both containers are healthy; ports remain 18661/18662; `/readyz` returns ready with identity_resolution_configured=true. All 50 image Python files match the checkout. Image ID: `sha256:e76b042ae76faf89cd73f34096bf19c090ab7ae2fa5dce6c00a84e8f6cbb9a05`; source-tree digest `dfa7aea08ce245c88b7dac663ce9ae2878ac4799f0fcd70ebbd7270b0c657396`. The service tuple is updated in `issue-361-service-runtime.json`, still PARTIAL_NOT_REPLAY_ACCEPTANCE.

All prior commits were pushed normally without rewriting history. PR #370 now describes the final signing/runner/mapping-binding implementation. GitHub Actions run `42798315355` on exact head `3d195443` completed with 11 successful checks and fundamental-release-gate skipped. This CI does not establish full cohort replay or release acceptance. No review approval or merge is asserted, and both #361/#369 remain OPEN.

The private project key has an identical mode-0600 recovery copy in the primary project's ignored `.audit/issue-361-signing/project-signer.pem`, so eventual issue-worktree cleanup can preserve the authorized project identity. Neither key copy is committed, printed or included in Docker context. Only the public identity and signed evidence are committed. Issue resources remain in use while acceptance is incomplete.

## Historical regulatory-validation diagnostic

Strict historical validation on exact `7d45e6ef3342b205685b1465ffeca9d0e1a54500` failed with exit 1, `DQC_VALIDATION_UNAVAILABLE`. Content-addressed diagnostic `issue-361-parser-diagnostic-v1/e59bfd0587fcbbdcce05c2d92880a77efbffea42c189ed9cf27207e7a58de088.json.gz` records the exact script, command, original source hash and output hash. Original exploratory acquisition lacks a complete response receipt and remains diagnostic only. [Blocker #371](https://github.com/sosodennis/value-investment-agent/issues/371) was opened immediately. The actual EFM log says EDGAR disables the separate DQC plugin. Pinned EDGAR `loadDqcRules` requires US GAAP year >=2020, whereas the original sample uses `http://fasb.org/us-gaap/2014-01-31`. No plugin or supported-year settings were changed.

The parser follow-up retains typed validation-failure evidence across its worker boundary, classifies this case as `DQC_TAXONOMY_UNSUPPORTED`, rejects incomplete DQC/XULE execution and preserves semantic EFM findings. Working-tree checks passed 26 parser tests/7 skipped; the configured real historical failure test passed and compared two identical diagnostic digests. An earlier complete run before semantic-finding retention passed 390 tests/26 skipped. These are preparation checks, not exact-commit or historical release acceptance. CI run `42798869087` on `7d45e6ef` finished with 11 successes and one skipped release gate. The issue, PR, historical approvals, complete cohort replay and threshold remain unverified. Next: exact-commit tests/diagnostic repeats, then a genuinely compatible audited historical validation profile and independent mapping/policy review.

## Exact parser diagnostic and label mapping boundary

Parser checkpoint `1f24bb80b39e5de8a6cd15203fd8a047ebe3c6a7`: 392 offline tests/26 skipped, 17 PostgreSQL tests, focused five-file runner/signing mypy, Ruff and architecture guard passed. Host diagnostic input `5c9e3037e0f6c19aadfb15ea3c3e0429b5c1b0911e38ca8bf4cd4dee5c572137` produced artifact `ac640836fca98f266eaabfa073ee8127b18570ac248e9c330296b64a5cde65df`; second run reused it with wrote=false. Each host attempt exited 1 with stable diagnostic `be5f4007d74d1a6f64c944a09307524e06b820b8c5231f0e5be1577ee42b3b32`. Rebuilt issue Docker image `sha256:7d4f082f350a808fe4e9de3e640247b677f40c82f4e35ee32af9fc11a595b8ab` matched all 50 Python sources, was healthy, and returned the same unsupported historical DQC result twice. Its Python 3.12.16 profile produced diagnostic `d064b97d2f18cdd900bed0e20684dcbeaa954fd254dbdb050be705e29affb9b7`; the host uses different pins, so cross-runtime digest equality is not claimed. Verification artifact `587c148a4e270aa8451ff8bbfe8ed23e3043e2de236cd85390dcd03fbc382232` retains complete command/script/output evidence and the initial Docker fixture ownership failure. No production profile, supported years or shared resources were changed.

The next source change binds OOS labels to the same checked mapping contract as forecasts. Mapping validation now runs in `read_valuation_evidence`, which returns an additive optional mapping_version; production missing metadata still fails. Replay checks the fixed mapping pin for both forecast and label evidence. Working-tree tests passed 394 offline/26 skipped and 20 runner/preparation tests; focused runner mypy and Ruff/format passed. Application mypy retains the same 11 diagnostics; parser retains the same 3; no full type acceptance is asserted. The first contract generation failed because openapi-typescript was not installed; npm ci exited 0, rerunning generation exited 0, and no generated tracked file changed. Next: commit and verify exact source, rebuild only the issue stack, update PR370/CI. #369/#371 and actual reviewed releases/full replay remain open.


Exact source verification: `7d1d2d782d439e47acf90c72ee03f1b203ab0757` passed 394 offline tests/26 skipped, 17 isolated PostgreSQL tests, the real historical failure-retention test (two identical diagnostics), focused five-file mypy, all 27 changed Python format checks, service Ruff, architecture guard, contract generation and diff checks. Existing project signatures both verified; key/identity initialization reused the originals with wrote=false. Image `sha256:13296bb92b4044596e5eaff46e909d2dd4d84757939fbc785c35594b3e2b39d8` matches all 50 Python source files and is healthy; the live OpenAPI includes the checked mapping_version response field. Verification input digest `4162c0a38cbf7f42e81b77d61068629dff97b95cc63511812f11a08c8b34cfef`, output digest `4655f52e140c767c44c00df1659945e3f6b2fe1a502c5f19e4d1c157d489d9b3`, report `a98a18a9b6932b1591922647bcc508d5d698bb7d69611dc066db9afecf6ded75` in issue-361-verification-v1. Recreating this engineering report returned the same digest/wrote=false; this is not a full cohort replay repeat. The runtime tuple is updated to this exact source. Full module type baselines, #369/#371, independent review, canonical historical releases and actual fixed-cohort replay remain outstanding; supported_history_threshold remains null. PR370 remains draft and no issue is closed.


Historical DQC candidate checkpoint for #361, exact execution SHA `8970281cd954e6f649877754033c31721fc705da`: [diagnostic evidence](issue-361-historical-dqc-candidate.md). Official v1 ran on the original US GAAP 2014 sample and selected pass/fail variations from all seven rule families. Two actual 14-case executions produced identical semantic output `28d463ce25a7e563af72091bb87c3bc3173519d9798b93e2573fcf7d4376bbaa`, zero network attempts, and second publication wrote=false. Input `fc0112433800de77a8721ebe29a40674676344fb5ad9781be13d596bf7f1661d`; verification `6b0c940e5570e4635e02876d838da6d11a139613516c157e30401780061e7e71`. Initial missing-taxonomy failures are retained. Existing project seals/key reuse and all 11 signing tests passed, together with Ruff, architecture guard and diff checks. This is code/count sample evidence: 2,335 official variations, severity equivalence, later taxonomy coverage and Docker candidate verification remain unverified. Next is a coherent historical validation contract after those checks; no production profile, independent approval, full replay or threshold promotion is asserted. #361/#369/#371 remain open and PR370 stays draft.
