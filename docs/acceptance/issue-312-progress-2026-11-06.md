# Issue 312 progress checkpoint

This is an engineering progress record for issue #312. It is not an
acceptance or VERIFIED record.

## Checkpoint

- Branch: `codex/issue-312-sec-ingestion`
- Worktree: `../value-investment-agent-issue-312-sec-ingestion`
- Base: `origin/main` at `bee63cb37da9edb2deb444e14d2fc666aed73d06`
- Prior implementation checkpoints: `48cbf3067cf1872b632e5020a8e6263e4d636929`,
  `6422a7cd`, `4adb1b9f`, `3bc35cd3`
- GitHub PR: none created

The implementation checkpoint contains the SEC acquisition boundary, typed
ingestion contract, PostgreSQL metadata migration, content-addressed source
capture, Arelle parser boundary, and focused source-acquisition tests. The
worktree was clean after that commit.

## DQC and Arelle research

The public DQC usage guidance was inspected at
<https://github.com/DataQualityCommittee/dqc_us_rules/blob/master/usage_rulesets.md>.
It confirms that DQC rulesets can carry local taxonomy packages for offline
execution. Using `--xule-bypass-packages` makes Arelle resolve package resources
from the DQC repository instead, so that mode is unsuitable for a deterministic
offline replay profile.

## Public filing probe

The probe used the public Apple 2024 10-K filing fixture at
`/tmp/issue312-aapl-validation-v3/filing/aapl-20240928.htm`.

- Filing SHA-256: `a14d584e9804a87e92ddbd2446ade975e926a494671292403c811c1f4fc4b846`
- Pinned runtime: Arelle 2.47.4, EFM 26.3, DQC US rules V31.0.3, XULE 30055
- Online warm-up command used the pinned EDGAR/XULE plugins, the DQC 2024
  ruleset, `--workOnline`, and an isolated taxonomy cache at
  `/tmp/issue312-aapl-validation-v3/taxonomy-online`.
- The warm-up fetched the missing public SEC exchange taxonomy, including
  `https://xbrl.sec.gov/exch/2024/exch-2024.xsd`; the cache reached 463 files
  and 57 MB.
- The resulting log was
  `/tmp/issue312-aapl-validation-v3/arelle-online.xml` and reported 73 entries,
  one EFM error (`EFM.5.02.05.disallowedElement` for the filing's inline XBRL
  `script` element), no `IOerror`, no `ValidationIncomplete`, and
  `validated in 418.99 secs`.

This probe demonstrates that the previously observed offline `IOerror` was a
missing captured exchange taxonomy resource. It does not prove that the
service's capture manifest, cache digest, or offline replay is complete.

## Parser validation checkpoint

- Unit command: `uv run --project fundamental-service pytest fundamental-service/tests/test_arelle_parser.py -q`
- Unit result: exit 0, 9 passed, 1 environment-gated integration test skipped.
- Ingestion command: `uv run --project fundamental-service pytest fundamental-service/tests/test_ingestion.py -q`
- Ingestion result: exit 0, 1 passed.
- Full service command: `uv run --project fundamental-service pytest fundamental-service/tests -q`
- Full service result: exit 0, 160 passed, 6 skipped, 2 warnings.
- Offline Apple EFM/DQC command (exit 0, 1 passed):
  `ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online uv run --project fundamental-service pytest fundamental-service/tests/test_arelle_parser.py::test_apple_sec_efm_dqc_replay_with_pinned_runtime -q`
- Filing fixture: Apple 2024 10-K, SHA-256
  `a14d584e9804a87e92ddbd2446ade975e926a494671292403c811c1f4fc4b846`.
- Pinned runtime: Arelle 2.47.4, SEC EFM 1.26.3, DQC US v31.0.3, Xule 30055,
  and the 2024 US-GAAP ruleset. The deadline worker forbids socket connections.
- Result: 1,127 parsed facts; executed engines `sec-efm` and `dqc-us`; evidence
  `strict-sec-efm-profile-selected` and `dqc-dqcrt-checks-completed`.
- Filing findings include blocking `EFM.5.02.05.disallowedElement` for the
  inline `script`, plus non-blocking SEC transform diagnostics. The parser
  preserves the blocking result; it does not mark this filing verified.
- Two sequential in-process replays with the same pinned runtime returned the
  same fact count, finding codes, engines, and execution evidence.
- Arelle initializes its `DisclosureSystem.Types` hook cache before the SEC
  plugin is dynamically registered. Clearing that cache after registering SEC
  and DQC plugins makes the strict SEC profile select successfully and sets
  `EFMplugin=true`.
- The service parser now uses Arelle's synchronous filing lifecycle for SEC
  validation. The deadline worker drains its result queue while the parser
  runs, avoiding a pipe deadlock when a complete fact report exceeds pipe
  capacity. Production ingestion now passes its request deadline to the parser.

## Remaining verification

- Capture and verify the complete taxonomy manifest and directory digest used
  by the service profile.
- Run the issue #312 contract, authentication, PostgreSQL concurrency,
  fault-injection, replay, Docker health, and Agent client checks against one
  exact commit.
- Record any expected filing-level EFM findings according to the service's
  quality policy before deciding whether the result is `degraded`, `abstain`, or
  publishable.

## Parser review checkpoint

- Read-only review target: `7410889b61b3eacab264efd309d9acbb86032ad3`.
- Review finding: validation mode downgraded every `model.errors` code absent
  from the XML log to a warning. An unlogged blocking DTS/XBRL error could
  therefore be omitted from `blocking_finding_codes()`.
- Fix: only the explicitly allowlisted Inline XBRL transformation diagnostics
  remain warnings; other unlogged Arelle model errors are recorded as errors.
- Regression: an unknown unlogged model error remains blocking while the
  allowlisted transformation diagnostic remains non-blocking.
- Implementation checkpoint: `247f8e04b148e36e0df307323cebb5707043b5f9`
  (`fix(fundamental): keep unlogged XBRL errors blocking (Refs #312)`).
- `git diff --check`: exit 0 before commit.
- Commit hooks: trailing whitespace, end-of-file, large-file, Ruff, and
  Ruff-format checks passed during `git commit`.
- Exact-SHA service command (run on the implementation checkpoint above,
  exit 0):

  ```sh
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online uv run --project fundamental-service pytest fundamental-service/tests -q
  ```

- Result: `162 passed, 5 skipped, 2 warnings` in 16.12 seconds. The Apple
  offline SEC EFM/DQC replay ran in this suite. Five environment-gated checks
  remained skipped; the two warnings are the existing Starlette/httpx
  deprecation and calculator Pydantic serialization warning.
- This checkpoint does not cover PostgreSQL coalescing, crash recovery,
  complete taxonomy-manifest validation, Docker health, or Agent client
  acceptance. No PR was created and issue #312 remains open.

## SEC validation dependency checkpoint

- Implementation commit: `d50cfbda071d67b44fc6b242c792db6510ed27d9`
  (`fix(fundamental): lock SEC validation runtime dependencies (Refs #312)`).
- Added direct bounded dependencies for the pinned SEC EFM plugin imports:
  `aniso8601` (10.0.1), `holidays` (0.108), and `pytz` (2026.6). This makes
  the runtime reproducible from the service lock instead of relying on packages
  that happened to be present in a developer virtual environment.
- `uv lock --check --project fundamental-service`: exit 0 (`Resolved 54
  packages`).
- Exact implementation SHA test command (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online \
  fundamental-service/.venv/bin/pytest -q fundamental-service/tests
  ```

- Result on `d50cfbda071d67b44fc6b242c792db6510ed27d9`: `167 passed, 2
  warnings` in 15.80 seconds. The suite had no skips. It includes the offline
  Apple 2024 10-K EFM/DQC parser replay; the two warnings are the existing
  Starlette/httpx deprecation and calculator Pydantic serialization warning.
- Compose project: `value-investment-agent-issue-312-sec-ingestion`; required
  host ports: PostgreSQL `18481`, Fundamental service `18082`. The earlier
  root `docker-compose.yml` config check was not the Fundamental stack and is
  superseded by the corrected check below. The actual stack is configured by
  `compose/verification/docker-compose.issue280-operations.yml` plus
  `compose/verification/docker-compose.issue312-sec-ingestion.yml`.
- Container import check exited 0 and reported `aniso8601 10.0.1`,
  `holidays 0.108`, and `pytz 2026.6`.
- Runtime resource fingerprints were recomputed from the pinned runtime and
  match the service configuration: taxonomy manifest
  `sec-us-gaap-2024-test-release`, taxonomy cache
  `23201023716b144aefca4864bc6e4ee055aad864f2e13f3ff1ef652354a1d42c` (464
  files), EDGAR plugin
  `63e4b5540a6754a1d6ad86a34ec1aa70f3f7da90e46c6fa3959686d8b2ac7330`, Xule
  plugin `e32ff88b52df8bf1e6aca3e63edabbc0b2f3513b7d0627ca9163db00d2a5678b`,
  and DQC ruleset
  `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930`.
- Current GitHub state at this checkpoint: issue #312 is open, no #312 PR
  exists, and branch `codex/issue-312-sec-ingestion` is twelve commits ahead
  of `origin/main` at
  `bee63cb37da9edb2deb444e14d2fc666aed73d06`. This progress record is not an
  acceptance or `VERIFIED` record.
- Remaining acceptance: live authenticated ingestion through the Docker API;
  cross-process PostgreSQL coalescing for at least 50 identical requests;
  distinct-key non-coalescing; provider/parser/storage/process fault recovery;
  atomic publication and authorization/audit checks; retained-evidence offline
  rebuild and clean-environment replay; and Agent client acceptance. The Apple
  parser fixture contains blocking EFM finding
  `EFM.5.02.05.disallowedElement`; the subsequent publication-gate verification
  below confirms that it is rejected before snapshot/fact publication.

## Blocking EFM publication-gate verification

- Follow-up inspection confirmed the suspected `created`/`VERIFIED` path is
  guarded before publication. `parsed_facts_to_candidates()` raises
  `PARSER_VALIDATION_BLOCKED` when `blocking_finding_codes()` is non-empty;
  `SecAcquisitionUseCase.execute()` catches that `SnapshotError`, records the
  failed audit outcome, and returns a non-retryable 422 before
  `publish_sec_ingestion()` can persist the snapshot or facts.
- The concern was not a production defect, so no status-only workaround or
  quality mutation was added. Such a mutation would be too late because the
  canonical rebuild boundary already rejects the filing.
- Verification command (exit 0):

  ```sh
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online \
  fundamental-service/.venv/bin/pytest -q \
    fundamental-service/tests/test_arelle_parser.py::test_apple_sec_efm_dqc_replay_with_pinned_runtime \
    fundamental-service/tests/test_sec_rebuild.py
  ```

- Result: `7 passed` in 4.54 seconds. The real Apple EFM/DQC replay reports
  `EFM.5.02.05.disallowedElement` as blocking, and the rebuild tests verify that
  a blocking parser finding raises `PARSER_VALIDATION_BLOCKED` rather than
  yielding canonical facts. This does not replace the still-required live
  authenticated Docker API acceptance test or the database concurrency and
  fault-recovery suites.

## PostgreSQL SEC pacing callback checkpoint

- Failure reproduction: the first live signed AAPL ingestion call returned
  HTTP 500 `internal_failure` before making a SEC request. A direct invocation
  of the same configured use case exposed
  `TypeError: PostgresMetadataStore.reserve_sec_provider_request_slot() takes 1
  positional argument but 2 were given`.
- Root cause: `SecEdgarSourceAdapter` defines and invokes the pacing callback as
  `Callable[[float], float]`, while the PostgreSQL implementation made the
  interval keyword-only. `db57b1feb9102597288628794eb02bcdef8603ab` removes that
  signature mismatch. Existing keyword callers remain valid.
- Regression test:
  `FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental fundamental-service/.venv/bin/pytest -q fundamental-service/tests/test_postgres_metadata.py::test_postgres_sec_request_slot_matches_source_adapter_callback`
  failed before the fix with the callback TypeError and passed after it (`1
  passed`, exit 0). The test uses a real PostgreSQL metadata store and a fake
  SEC HTTP response, so it validates the cross-module contract without network
  access.
- Exact commit `db57b1feb9102597288628794eb02bcdef8603ab` full service suite
  command (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online \
  fundamental-service/.venv/bin/pytest -q fundamental-service/tests
  ```

- Result on the exact commit: `168 passed, 2 warnings` in 16.11 seconds, no
  skips. `uv lock --check --project fundamental-service` and
  `git diff --check` both exited 0. Commit hooks passed trailing whitespace,
  end-of-file, large-file, Ruff, and Ruff-format checks.
- Corrected Compose check (exit 0) used the actual two-file service stack,
  project `value-investment-agent-issue-312-sec-ingestion`, PostgreSQL host
  port `18481`, service host port `18082`, and the pinned SEC resource paths
  and hashes:

  ```sh
  COMPOSE_PROJECT_NAME=value-investment-agent-issue-312-sec-ingestion \
  FUNDAMENTAL_POSTGRES_HOST_PORT=18481 \
  FUNDAMENTAL_SERVICE_HOST_PORT=18082 \
  FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256=23201023716b144aefca4864bc6e4ee055aad864f2e13f3ff1ef652354a1d42c \
  FUNDAMENTAL_SEC_TAXONOMY_CACHE_HOST_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online \
  FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256=63e4b5540a6754a1d6ad86a34ec1aa70f3f7da90e46c6fa3959686d8b2ac7330 \
  FUNDAMENTAL_SEC_EDGAR_PLUGIN_HOST_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256=e32ff88b52df8bf1e6aca3e63edabbc0b2f3513b7d0627ca9163db00d2a5678b \
  FUNDAMENTAL_SEC_XULE_PLUGIN_HOST_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  FUNDAMENTAL_SEC_DQC_RULESET_SHA256=0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930 \
  FUNDAMENTAL_SEC_DQC_RULESET_HOST_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  docker compose -p value-investment-agent-issue-312-sec-ingestion \
    -f compose/verification/docker-compose.issue280-operations.yml \
    -f compose/verification/docker-compose.issue312-sec-ingestion.yml config --quiet
  ```

- The same two-file Compose stack rebuilt only `fundamental-service` from the
  exact commit; the database volume and container were retained. Build command
  exited 0. New image ID:
  `sha256:025a86b338b5edd76b90997c6a879682eb9b247e20be1c438178ba96e19902da`.
  PostgreSQL and Fundamental service were both healthy. `curl -fsS
  http://127.0.0.1:18082/readyz` exited 0 with `{"status":"ready",
  "contract_version":"internal.v1"}`. A container import check exited 0 and
  reported `aniso8601 10.0.1`, `holidays 0.108`, and `pytz 2026.6`.
- Exact build command (exit 0; resource paths and digests are pinned values
  recorded in the preceding checkpoint):

  ```sh
  COMPOSE_PROJECT_NAME=value-investment-agent-issue-312-sec-ingestion \
  FUNDAMENTAL_POSTGRES_HOST_PORT=18481 \
  FUNDAMENTAL_SERVICE_HOST_PORT=18082 \
  FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256=23201023716b144aefca4864bc6e4ee055aad864f2e13f3ff1ef652354a1d42c \
  FUNDAMENTAL_SEC_TAXONOMY_CACHE_HOST_DIR=/tmp/issue312-aapl-validation-v3/taxonomy-online \
  FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256=63e4b5540a6754a1d6ad86a34ec1aa70f3f7da90e46c6fa3959686d8b2ac7330 \
  FUNDAMENTAL_SEC_EDGAR_PLUGIN_HOST_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256=e32ff88b52df8bf1e6aca3e63edabbc0b2f3513b7d0627ca9163db00d2a5678b \
  FUNDAMENTAL_SEC_XULE_PLUGIN_HOST_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  FUNDAMENTAL_SEC_DQC_RULESET_SHA256=0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930 \
  FUNDAMENTAL_SEC_DQC_RULESET_HOST_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  docker compose -p value-investment-agent-issue-312-sec-ingestion \
    -f compose/verification/docker-compose.issue280-operations.yml \
    -f compose/verification/docker-compose.issue312-sec-ingestion.yml \
    up -d --build fundamental-service
  ```
- Live API check used a correctly signed `internal.v1` context, Bearer
  credential, authorized organization `org-sec-ingestion-test`, the persisted
  approved `sec-revenue-v1` mapping, AAPL CIK `0000320193`, and filing
  `0000320193-24-000123` at cutoff `2024-11-05T00:00:00Z`. The first attempt
  before the fix returned HTTP 500 as described above. The retry through
  `/v1/data/ingestions` on the rebuilt image returned HTTP 422 with stable code
  `PARSER_VALIDATION_BLOCKED` and `retryable=false`. The SEC audit table records
  this exact outcome and caller/organization/correlation. The filing's pinned
  offline EFM/DQC replay reports blocking
  `EFM.5.02.05.disallowedElement`; zero ingestion acquisitions and zero
  canonical facts were published. This proves the error path is fail-closed,
  not the successful snapshot publication criterion.
- Remaining acceptance includes a successful live SEC snapshot/fact
  publication, 50-way cross-process PostgreSQL request coalescing, distinct
  acquisition-key isolation, injected provider/parser/storage/process failures
  and recovery, atomic visibility, persisted audit/auth rejection cases,
  clean offline retained-evidence replay, and Agent client acceptance. No PR
  has been created and #312 remains open.

## Microsoft DQCRT coverage diagnosis

- Official SEC submissions metadata identifies Microsoft's 2024 10-K as CIK
  `0000789019`, accession `0000950170-24-087843`, filed `2024-07-30`, with
  primary document `msft-20240630.htm`:
  <https://data.sec.gov/submissions/CIK0000789019.json>.
- The live SEC document SHA-256 is
  `577d30abb4f61409b3c5ad9c332a408970ed7e54fd284a7ed483605b974cb90f`.
  Its extension schema imports the FASB `us-gaap/2023` namespace. The SEC
  accession's public XBRL package is
  <https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/0000950170-24-087843-xbrl.zip>
  with SHA-256
  `5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82`.
- The pinned SEC EDGAR plugin README says 2023-2024 US-GAAP filings use its
  Python DQCRT implementation, while 2025-and-newer use Xule:
  <https://github.com/Arelle/EDGAR/blob/4891c4c9889c77af247428ceff4fa7cc52d534ea/readme.md>.
  Arelle's 2.47.4 source confirms `profileActivity` only emits its completion
  record when elapsed time exceeds `minTimeToShow`:
  <https://github.com/Arelle/Arelle/blob/2.47.4/arelle/ModelXbrl.py#L1203-L1227>.
  The SEC plugin documents that `loadDqcRules` may return an empty collection
  at <https://github.com/Arelle/EDGAR/blob/4891c4c9889c77af247428ceff4fa7cc52d534ea/validate/Filing.py#L219-L220>
  and calls `"... DQCRT checks"` after the rules loop at
  <https://github.com/Arelle/EDGAR/blob/4891c4c9889c77af247428ceff4fa7cc52d534ea/validate/Filing.py#L5779>.
  The completion message alone therefore does not prove that DQCRT rules ran.
- Read-only inspection of the pinned offline cache found 464 files (57 MB)
  and `us-gaap-2024.xsd`, but no `us-gaap-2023.xsd`. A direct offline parser
  trace of the retained Microsoft filing plus its SEC-published extension
  schema reported `dqcRules` length `0` after `loadDqcRules`, no `xuleValidate`
  call, and `DQC_VALIDATION_UNAVAILABLE`. The DQCRT activity hook ran after
  `0.00145` seconds with `minTimeToShow=0.1`. The SEC code shows that this
  short duration followed an empty rule set, so lowering the telemetry
  threshold would conceal the missing taxonomy.
- A first host-side replay attempt supplied only the primary filing and not
  its extension schema, producing missing-schema findings before the intended
  check. That attempt is diagnostic only and is not acceptance evidence.
- Keep the current 2024 cache. Prepare a separate, hashed offline taxonomy
  release with the filing-referenced 2023 and 2024 public resources. Update
  the release pin and manifest description to identify that bundle. Rerun the
  Microsoft filing offline with its schema and the pinned EFM/DQC runtime.
  The signed ingestion remains unaccepted until DQC rules execute and a filing
  with no blocking EFM/DQC findings publishes a snapshot and facts.
- No parser workaround, `VERIFIED` state, PR, or GitHub issue mutation was
  made. Issue #312 remains open with no PR.
