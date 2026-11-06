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
- Recommended next step at this point (completed in the later checkpoint
  below): preserve the 2024 cache and add a separately hashed offline taxonomy
  release with the filing-referenced 2023 and 2024 public resources. Update
  the release pin and manifest description to identify that bundle. Rerun the
  Microsoft filing offline with its schema and the pinned EFM/DQC runtime.
  The signed ingestion remains unaccepted until DQC rules execute and a filing
  with no blocking EFM/DQC findings publishes a snapshot and facts.
- No parser workaround, `VERIFIED` state, PR, or GitHub issue mutation was
  made. Issue #312 remains open with no PR.

## Canonical SEC archive and 2023/2024 DQCRT checkpoint

- Implementation commit: `2ec337da` (`fix(fundamental): capture canonical SEC
  filing archives (Refs #312)`). The `codex/issue-312-sec-ingestion`
  worktree was clean before this checkpoint and remains ahead of
  `origin/main` at `bee63cb37da9edb2deb444e14d2fc666aed73d06`.
- SEC submissions and accession index identify Microsoft's 2024 10-K as
  CIK `0000789019`, accession `0000950170-24-087843`, primary document
  `msft-20240630.htm`, accepted `2024-07-30T20:06:22Z`. The SEC index lists
  its XBRL archive as 551,435 bytes.
- Repeated direct SEC downloads returned HTML of 6,861,017 bytes with SHA-256
  `577d30abb4f61409b3c5ad9c332a408970ed7e54fd284a7ed483605b974cb90f` and
  one CDN challenge script. The official accession ZIP SHA-256 is
  `5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82`.
  Its canonical HTML member is 6,860,910 bytes with SHA-256
  `01cc7750e904e14a2065ba0ddb639138f2e5b0591c8071a513ac1234a735602e`;
  it has no challenge script. The ZIP's extension schema imports
  `http://fasb.org/us-gaap/2023`.
- `SecEdgarSourceAdapter` now captures only the accession-matched
  `*-xbrl.zip` for filing bytes. Ingestion verifies the ZIP directory, limits
  archive bytes, member count, total uncompressed bytes and selected member
  sizes, rejects duplicate names/encrypted or missing members, and reads only
  the indexed root-file set without extracting archive paths. The content
  store retains the raw ZIP, canonical filing member and selected DTS
  resources independently by hash. Fact provenance references the canonical
  member; the SEC ZIP is the original package evidence. The archive source is
  included in the release-security SEC host/path allowlist.
- The small committed Microsoft test package contains only the canonical HTML
  and its SEC extension schema, recompressed for regression testing. Its SHA
  is `9315745e8b66735afd8be0f63a2d5876d350eb7ae7be80a7e0aff015df76acf0`.
  The original 551,435-byte SEC archive remains independently identified by
  its public URL and hash above; the full binary is not copied into Git.
- The SEC taxonomy runtime defaults now identify the tested
  `sec-us-gaap-2023-2024-public-bundle` / `us-gaap-2023-2024` release rather
  than describing the cache as 2024-only.
- Exact-SHA focused source command (exit 0):

  ```sh
  fundamental-service/.venv/bin/pytest -q \
    fundamental-service/tests/test_ingestion.py \
    fundamental-service/tests/test_source_acquisition.py \
    fundamental-service/tests/test_sec_source.py
  ```

- Result on `2ec337da`: `11 passed` in 1.40 seconds.
- Exact-SHA Microsoft EFM/DQC and fixture-manifest command (exit 0):

  ```sh
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-sec-taxonomy-2023-2024 \
  fundamental-service/.venv/bin/pytest -q \
    fundamental-service/tests/test_arelle_parser.py::test_microsoft_sec_efm_dqc_replay_uses_canonical_sec_archive_bytes \
    fundamental-service/tests/test_arelle_parser.py::test_sec_capture_manifest_has_verified_hashes_and_amendment_metadata
  ```

- Result: `2 passed` in 5.52 seconds. The Microsoft offline parser replay
  reports 1,856 facts, selects strict SEC EFM and DQC US engines, reports
  `dqc-dqcrt-checks-completed`, has no blocking findings, and records no
  network attempts. The test verifies the exact SEC archive member bytes and
  schema. The taxonomy bundle SHA-256 is
  `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`.
- `uvx --from ruff ruff format --check` on all eight changed Python files:
  exit 0. `uvx --from ruff ruff check --select E,F,I --ignore E501` on the
  changed Python files: exit 0. `git diff --check`: exit 0. Commit hooks for
  whitespace, YAML, large files, Ruff, and Ruff formatting all passed.
- This is an implementation checkpoint, not acceptance or `VERIFIED`.
  PostgreSQL-backed authenticated SEC ingestion has not yet been rerun against
  the 2023/2024 cache on the rebuilt Docker image. Remaining acceptance still
  includes a published snapshot/facts from a clean filing, cross-process
  concurrency, distinct-key isolation, failure/recovery and atomicity,
  authorization/audit checks, retained-evidence offline rebuild, and Agent
  client acceptance. No PR has been created and #312 remains open.

## Authenticated SEC publication and profile propagation checkpoint

- Implementation commit: `28c1d42ad0cd1102eb8e61ffe4c2dd046c68e5c6`
  (`fix(fundamental): bind SEC ingestion to validation profile (Refs #312)`).
- The previous live request returned HTTP 400 `invalid_request` before an audit
  row or acquisition was created. `SecIngestionResponseV1` requires a
  validation profile ID and digest, but `SecAcquisitionUseCase` omitted both.
  The persisted snapshot also lacked the profile fields because it was built
  before parsing. The fix derives both response values from the actual Arelle
  report and binds them into the final snapshot manifest after parsing. The
  runtime profile ID is the request's contract-limited selector.
- Regression assertions verify that snapshot profile ID and digest match the
  parser report. Focused command:
  `fundamental-service/.venv/bin/pytest -q fundamental-service/tests/test_ingestion.py fundamental-service/tests/test_source_acquisition.py`
  Result: exit 0, `3 passed`.
- Exact-commit service suite command (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-sec-taxonomy-2023-2024 \
  fundamental-service/.venv/bin/pytest -q fundamental-service/tests
  ```

- Result on `28c1d42ad0cd1102eb8e61ffe4c2dd046c68e5c6`: `171 passed, 2
  warnings` in 20.91 seconds, no skips. `uv lock --check --project
  fundamental-service`, `git diff --check`, Ruff format check, and Ruff
  `E,F,I` check all exited 0. Commit hooks for whitespace, end-of-file,
  large-file, Ruff, and Ruff-format checks passed.
- Docker Compose used project `value-investment-agent-issue-312-sec-ingestion`,
  PostgreSQL host port `18481`, and service host port `18082`. The validated
  stack services were `fundamental-postgres` and `fundamental-service`;
  `docker compose ... config --quiet` exited 0. The Fundamental service image
  was rebuilt from this code and both containers reported `healthy`;
  `GET http://127.0.0.1:18082/readyz` returned `{"status":"ready",
  "contract_version":"internal.v1"}`.
- Authenticated live request command was run with
  `PYTHONPATH=finance-agent-core:. fundamental-service/.venv/bin/python -`
  using `build_internal_context`, Bearer `integration-token`, organization
  `org-sec-ingestion-test`, and POST `/v1/data/ingestions`. It selected
  Microsoft CIK `0000789019`, accession `0000950170-24-087843`, cutoff
  `2025-06-30T00:00:00Z`, approved `sec-revenue-v1` mapping, Arelle `2.47.4`,
  and the pinned `sec-efm-us-dqc-v31.0.3` profile with the 2023/2024 taxonomy
  package. Command exit 0; API result HTTP 200, `degraded` / `provisional`,
  with 57 canonical fact IDs and no blocking parser findings. Reported finding
  codes were `EFM.5.02.05.14.hidden-fact-eligible-for-transform`,
  `EFM.6.05.42`, and `ixbrl:selfClosedTagWarning`; the result was not upgraded
  to `verified`.
- Published immutable reference: snapshot
  `snapshot-416fe2f64c7aff737286ba04326397be`, manifest digest
  `436bcb6b938cfd0ffa1ac9f6f5cd5fef88e49f0bfb028f3b806fd56aaef37f8f`,
  validation profile digest
  `a5a2f617ea7872d2e3ba3d79abb93cd19ba7cd6773352edc77fe33284534da5a`,
  taxonomy package `sec-us-gaap-2023-2024-public-bundle`, and five source
  content hashes. PostgreSQL confirms one acquisition row, one snapshot, 57
  `snapshot_facts` links, and one `degraded` audit row for correlation ID
  `issue-312-live-msft-profile-fix`.
- A second signed request with the same acquisition input and a new correlation
  ID returned HTTP 200 `reused=true` with the same snapshot ID and manifest
  digest. PostgreSQL still contained one acquisition row; a second audit row
  records `reused` with five source hashes.
- Public-source research: the official
  [DQC ruleset usage guide](https://github.com/DataQualityCommittee/dqc_us_rules/blob/master/usage_rulesets.md)
  states that ruleset ZIPs include local taxonomy packages for offline
  execution; `--xule-bypass-packages` resolves resources from the DQC
  repository and therefore is unsuitable for deterministic offline replay.
  Official issue searches found DQC rule issue
  [#1012](https://github.com/DataQualityCommittee/dqc_us_rules/issues/1012),
  a closed DQC.US.0159 nil-fact crash for V30, and Arelle EDGAR issue
  [#41](https://github.com/Arelle/EDGAR/issues/41), concerning IFRS validation
  messages. Neither matches this US-GAAP V31 failure. The direct cause was the
  missing 2023 US-GAAP taxonomy resource, already fixed and verified by the
  1,856-fact offline Microsoft EFM/DQC replay above.
- Issue #312 remains open with no PR. This checkpoint is not an acceptance or
  `VERIFIED` record. Remaining criteria include 50-way cross-process
  coalescing, distinct-key isolation, provider/parser/storage/process fault
  recovery, atomic publication, authorization failures and audit evidence,
  retained-evidence clean offline rebuild, and Agent client acceptance.

## SEC ingestion acceptance checkpoint

- Code checkpoint: `18a1f7cc` (`test(fundamental): recover SEC lock after
  process failure (Refs #312)`). It includes the service and Agent client
  changes from `40b5c034`; the later commits only add PostgreSQL acceptance
  tests. Branch `codex/issue-312-sec-ingestion` remains based on
  `origin/main` `bee63cb37da9edb2deb444e14d2fc666aed73d06`. The worktree was
  clean after the code checkpoint. Issue #312 remains open and has no PR.
- PostgreSQL cross-process HTTP coalescing command (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
    fundamental-service/.venv/bin/pytest -q \
    fundamental-service/tests/test_postgres_metadata.py::test_fifty_sec_ingestion_contenders_across_processes_publish_once
  ```

- The test starts ten OS processes with five signed `/v1/data/ingestions`
  requests each against real PostgreSQL. The canonical request key is derived
  from the actual `SecIngestionRequestV1`. Exactly one request publishes, 49
  receive retryable `INGESTION_IN_PROGRESS`, the provider probe records one
  call, and 50 subsequent route retries return `reused` with one identical
  snapshot ID and manifest digest. PostgreSQL audit outcomes are 49
  `INGESTION_IN_PROGRESS`, one `degraded`, and 50 `reused`.
- Persisted authorization audit command (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
    fundamental-service/.venv/bin/pytest -q \
    fundamental-service/tests/test_postgres_metadata.py::test_unauthorized_sec_ingestion_is_rejected_and_audited_in_postgres
  ```

- A signed request from `org-unapproved` receives HTTP 403
  `INGESTION_NOT_AUTHORIZED`; a real PostgreSQL audit row records the derived
  acquisition key, principal `subject-test`, organization, correlation ID,
  empty source hashes, and outcome. Invalid/missing signed contexts are also
  covered at the route boundary.
- Process failure command (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
    fundamental-service/.venv/bin/pytest -q \
    fundamental-service/tests/test_postgres_metadata.py::test_terminated_ingestion_owner_releases_postgres_single_flight_lock
  ```

- A child OS process acquired the PostgreSQL advisory lock and was terminated.
  The parent could not acquire the same key before termination and acquired it
  immediately after the database session closed. The publication transaction
  failure/retry test also confirms that no manifest or fact remains visible
  after an injected metadata write failure.
- Final Fundamental service command on `18a1f7cc` (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
  fundamental-service/.venv/bin/pytest -q fundamental-service/tests
  ```

- Result: `181 passed, 2 warnings`, no skips. Warnings are the existing
  Starlette/httpx TestClient deprecation and calculator Pydantic serialization
  warning. Agent client command `uv run --project finance-agent-core pytest
  -q finance-agent-core/tests/agents/fundamental/test_fundamental_service_client.py`
  exited 0 with `4 passed`. `uv lock --check --project fundamental-service`,
  Ruff `E,F,I`, Ruff format check on all nine changed Python files, and
  `git diff --check` exited 0. Commit hooks passed on both test checkpoints.
- Docker project: `value-investment-agent-issue-312-sec-ingestion`; PostgreSQL
  host port `18481`, Fundamental service host port `18082`. The service image
  was built from the unchanged service source at `40b5c034`, image ID
  `sha256:d7e0982c551bc761368bab31e96637112ec335524e6c3f5456fc6cfc41e6feeb`.
  Both required containers were healthy; Compose `config --quiet` exited 0
  with the pinned resources. A first start used the 2024 taxonomy cache hash
  with the 2023/2024 mounted path and failed closed at startup. Recomputing the
  mounted cache hash corrected the configuration to
  `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`; the
  service then became healthy and `GET http://127.0.0.1:18082/readyz` returned
  `{"status":"ready","contract_version":"internal.v1"}`. No data volume
  was removed or reset.
- Authenticated live request used the signed `internal.v1` context, Bearer
  `integration-token`, authorized organization `org-sec-ingestion-test`,
  Microsoft CIK `0000789019`, accession `0000950170-24-087843`, valuation
  cutoff `2025-06-30T00:00:00Z`, and approved `sec-revenue-v1` mapping. Its
  policy version was uniquely pinned to `sec-public-pit-v2-checkpoint-40b5c034`
  so it could not reuse the earlier acquisition. POST
  `http://127.0.0.1:18082/v1/data/ingestions` exited 0 with HTTP 200,
  `status=degraded`, `quality_status=provisional`, 57 canonical fact IDs, no
  blocking parser findings, and no promotion to `verified`.
- New acquisition key:
  `0ffa4527f81ef61fdf50e4af50a0fc39f7a8a48bd341d21a98d336fe8cec26d7`.
  Published snapshot `snapshot-e48f2ab35591026b79fd289dcbd96ac2`, manifest
  digest `ebdc9d766fb6edcf4dda634f80a72a03dad819f2b8f191bbe0c1573e62db6e49`,
  and validation profile digest
  `a5a2f617ea7872d2e3ba3d79abb93cd19ba7cd6773352edc77fe33284534da5a`.
  PostgreSQL confirmed that the acquisition row and snapshot manifest both
  store the same acquisition key and digest, with 57 `snapshot_facts` links
  and one `degraded` audit row. The five referenced source hashes are
  `01cc7750e904e14a2065ba0ddb639138f2e5b0591c8071a513ac1234a735602e`,
  `5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82`,
  `5692bbfccc76991d2cba6f4ddf2a8db9487dfce51ac5dded0b2607660a65a966`,
  `1a4256a23be814a5193601a2c733d1da647c45da4d73dfe98eee58e32f8f9251`, and
  `0b71b0995cba38320a588bdeed7a516be06e1f681832ccb7f6d274bdb965d554`.
- The Agent `HttpFundamentalServiceClient.execute("ingest_sec_data", ...)`
  made a live signed request to the same endpoint with the same canonical
  input. It returned `status=reused`, `reused=true`, the same snapshot ID and
  digest, and all 57 fact references. The first caller's accidental
  attribute-style assertion exposed that the client result payload is a dict;
  the corrected assertion passed against the documented wire envelope.
- Retained-evidence replay copied the service-owned content volume to
  `/private/tmp/issue312-retained-evidence-40b5c034/content`. All five source
  objects passed SHA-256 verification. The original SEC ZIP and selected
  filing/taxonomy members were rebuilt into a clean temporary directory; a
  socket-connect guard recorded zero network attempts. Pinned offline replay
  reproduced 1,856 parser facts, `sec-efm` and `dqc-us` engines, no blocking
  findings, the same three non-blocking finding codes, taxonomy cache digest
  `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`, and the
  same validation profile digest. Re-running the approved mapping and
  point-in-time selection reproduced exactly the 57 persisted canonical fact
  IDs; every corresponding PostgreSQL fact record was present.
- The public DQC ruleset usage guidance and related DQC/Arelle issue search are
  recorded above. The successful live filing's three findings remain visible
  as degraded evidence; no paid provider or hidden fallback was used.
- Remaining before #312 PR: run the independent read-only review, resolve any
  findings and rerun affected checks; inspect the final diff against every
  #312 criterion; collect required GitHub CI on the exact pushed commit; and
  record any remaining intentionally unrun load/soak or deployment checks.
  No PR has been created, #312 is open, and no `VERIFIED` label has been added.

## Runtime-bound acquisition and capture-time checkpoint

- Implementation commit: `e31baf7c` (`fix(fundamental): bind SEC runtime
  releases to acquisition`). The worktree was clean at the start of this
  checkpoint and remains clean after the code commit. No PR was created and
  issue #312 remains open.
- The acquisition key payload now stores the deployed validation profile digest
  and taxonomy cache SHA-256. The same pinned `ArelleValidationProfileV1` is
  passed from request authentication/key derivation into the parser, so the
  key cannot describe one runtime while parsing with another. Snapshot
  publication now sets `captured_at` to at least every source record's capture
  time, and the public snapshot contract rejects manifests that violate this
  invariant.
- Focused regression command (exit 0):

  ```sh
  uv --project fundamental-service run pytest \
    fundamental-service/tests/test_source_acquisition.py \
    fundamental-service/tests/test_snapshots.py -q
  ```

  Result: `13 passed, 1 warning`.
- Fundamental service command on exact commit `e31baf7c` (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental \
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
  uv --project fundamental-service run pytest fundamental-service/tests -q
  ```

  Result: `183 passed, 2 warnings` in 26.75 seconds. The prior run with the
  2024-only `/tmp/issue312-aapl-validation-v3/taxonomy-online` intentionally
  failed closed (`1 failed, 182 passed`) because the Microsoft filing's 2023
  SEC taxonomy was absent; no parser change or fallback was used. Re-running
  with the retained 2023/2024 bundle passed the offline EFM/DQC replay.
- Docker Compose validation used project
  `value-investment-agent-issue-312-sec-ingestion`, PostgreSQL host port
  `18481`, Fundamental service host port `18082`, and only
  `fundamental-postgres` plus `fundamental-service`:

  ```sh
  COMPOSE_PROJECT_NAME=value-investment-agent-issue-312-sec-ingestion \
  FUNDAMENTAL_POSTGRES_HOST_PORT=18481 FUNDAMENTAL_SERVICE_HOST_PORT=18082 \
  FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256=0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3 \
  FUNDAMENTAL_SEC_TAXONOMY_CACHE_HOST_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
  FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256=63e4b5540a6754a1d6ad86a34ec1aa70f3f7da90e46c6fa3959686d8b2ac7330 \
  FUNDAMENTAL_SEC_EDGAR_PLUGIN_HOST_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256=e32ff88b52df8bf1e6aca3e63edabbc0b2f3513b7d0627ca9163db00d2a5678b \
  FUNDAMENTAL_SEC_XULE_PLUGIN_HOST_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  FUNDAMENTAL_SEC_DQC_RULESET_SHA256=0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930 \
  FUNDAMENTAL_SEC_DQC_RULESET_HOST_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  docker compose -p value-investment-agent-issue-312-sec-ingestion \
    -f compose/verification/docker-compose.issue280-operations.yml \
    -f compose/verification/docker-compose.issue312-sec-ingestion.yml \
    config --quiet
  ```

  Exit code was 0. Rebuilding `fundamental-service` from `e31baf7c` exited 0;
  the image digest was
  `sha256:168f53ec958afb10f5be73d6b11ebea82e82f84a6f4cce73617fe5daf34bc319`.
  PostgreSQL and Fundamental service reported `healthy`, and
  `GET http://127.0.0.1:18082/readyz` returned
  `{"status":"ready","contract_version":"internal.v1"}`.
- Signed live SEC ingestion against the rebuilt container exited 0 and
  returned HTTP 200 with `status=degraded`, `quality_status=provisional`, 57
  canonical facts, no blocking parser findings, and the pinned profile
  digest `a5a2f617ea7872d2e3ba3d79abb93cd19ba7cd6773352edc77fe33284534da5a`.
  The runtime-bound acquisition key was
  `5c806775229226ea7ac75a45e883aa91f1b51e3d8277c26998b503b801440fcc`.
  PostgreSQL records one immutable acquisition and five source hashes; the
  published snapshot is `snapshot-bbb253e0aa9ddba14b91bee79b3fbb3a` with
  manifest digest
  `95a6c8d7cc9c6c14cd7c4d039672cd83b3f621ebd9cb372c1a15c7e26d94b0a4`.
  Its persisted snapshot capture time is
  `2026-11-06T00:44:20.831373Z`, covering all five source record capture
  times. A second signed request with the same canonical input returned HTTP
  200 `status=reused`, `reused=true`, the same snapshot and manifest, and 57
  fact references. Audit rows for the two correlations are `degraded` and
  `reused`, each with five source hashes.
- Agent client acceptance, retained-evidence replay, and PostgreSQL
  concurrency/fault-injection evidence from the immediately preceding
  `18a1f7cc` checkpoint remain applicable to unchanged behavior. Checks not
  rerun after `e31baf7c`: the Agent client live command and independent
  retained-evidence replay. The full service suite includes the client
  contract and replay unit coverage; Docker live ingestion and reuse were
  rerun. Load/soak testing and deployment rollout remain intentionally out of
  scope for this issue.

## SEC multiline normalization and retained-evidence checkpoint

- Verified code commit: `72875fe2b4f30b60c93c59c09bb0e3f2bd256a15`
  (`fix(fundamental): normalize SEC multiline edge responses Refs #312`),
  based on `origin/main` `10a88e41f3f5d63ec9feebb472dbd4d5469c647f`. The
  worktree was clean before recording this evidence. No PR exists and #312
  remains open with its `blocker` label; this checkpoint does not mark the
  issue verified.
- Full Fundamental service suite command on the exact code commit (exit 0):

  ```sh
  FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental_test_72875fe2 \
  ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE312_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
  ISSUE328_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
  ISSUE328_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
  ISSUE328_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
  ISSUE328_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
  fundamental-service/.venv/bin/pytest -q fundamental-service/tests
  ```

- Result: `194 passed, 0 skipped` in 103.90 seconds. The two warnings are the
  existing Starlette/httpx TestClient deprecation and calculator Pydantic
  serialization warning. `python3 scripts/architecture_guard.py` exited 0
  with no boundary violations. `uv lock --check --project fundamental-service`
  exited 0. The Agent client command
  `uv run --project finance-agent-core pytest -q finance-agent-core/tests/agents/fundamental/test_fundamental_service_client.py`
  exited 0 with `4 passed`.
- Docker Compose project
  `value-investment-agent-issue-312-sec-ingestion` was inspected without
  changing containers or volumes. The issue-specific Compose configuration
  validated with `config --quiet` (exit 0) and lists only
  `fundamental-postgres` and `fundamental-service`. The service container was
  healthy on image `sha256:4b32db0b10a477f814802cc6f5072851ae9fdea50b038c948b41f301a9ff5e27`;
  `GET http://127.0.0.1:18082/readyz` returned
  `{"status":"ready","contract_version":"internal.v1"}`.
  The running image's parser pins were EDGAR plugin
  `054a21fa824797787acc2c6e98af4bb040c51bbee41b613cee1793db8fd144af`, Xule
  plugin `63123d67048019e3c49a0efde0e0aa8ec3eba0fc971da56ebd96dea8e40cd713`,
  and DQC ruleset
  `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930`.
- PostgreSQL schema was read directly from
  `information_schema.columns`. The acquisition table stores
  `acquisition_key`, `snapshot_id`, `fact_ids`, `result_payload`, and caller
  metadata; the manifest table stores `snapshot_id`, `manifest_digest`, and
  payload; audit rows store correlation, outcome, and source hashes. No
  acquisition digest column was assumed. On live acquisition key
  `a3a659859f6f2a08556d705f93175902051ea10fecdd638660010c5ee14704d8`,
  PostgreSQL records correlation `issue312-live-msft-4fe205a3-normalized`,
  snapshot `snapshot-960d616aab2cac8bd4a7c1cfe8f99492`, manifest digest
  `0ef7b562f1ee89c0e7635d3876e05fb128669f1567d4535514af3ac20d09407b`, and
  57 fact IDs. The manifest links to 57 distinct persisted facts. The matching
  retry correlation `issue312-live-msft-4fe205a3-reuse` returns the same
  snapshot and digest with `reused=true` and 57 references.
- Both persisted audit records use the same acquisition key and list the five
  acquired source hashes:
  `0bb3e310d6aafc4c2aa9f215d79f7b819b7862cc119ed6fe26c3b604ce75d536`
  (raw SEC filing),
  `5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82`
  (SEC ZIP archive),
  `5692bbfccc76991d2cba6f4ddf2a8db9487dfce51ac5dded0b2607660a65a966`
  (archive index),
  `1a4256a23be814a5193601a2c733d1da647c45da4d73dfe98eee58e32f8f9251`
  (submissions response), and
  `0b71b0995cba38320a588bdeed7a516be06e1f681832ccb7f6d274bdb965d554`
  (filing extension schema). The first audit outcome is `degraded` and the
  retry outcome is `reused`; the response remains `provisional` with no
  promotion to verified. The parser-integrity evidence records 12 non-blocking
  findings, zero blocking findings, SEC EFM and DQC-US engines, Arelle 2.47.4,
  DQC v31.0.3, Xule 30055, and the pinned profile and taxonomy digests.
- Retained source objects were read from the running service content volume and
  each SHA-256 was recomputed before replay. `assess_filing_response` classified
  the response as normalized under
  `sec-edgar-akamai-trailing-script-v2`: raw bytes are 6,861,030 bytes, the SEC
  index declares 6,860,911 bytes, and the ZIP member is 6,860,910 bytes. The
  raw response hash remains
  `0bb3e310d6aafc4c2aa9f215d79f7b819b7862cc119ed6fe26c3b604ce75d536`; the
  normalized bytes and exact canonical ZIP member both hash to
  `01cc7750e904e14a5193601a2c733d1da647c45da4d73dfe98eee58e32f8f9251`.
  Recorded removed ranges are `[6860895, 6861014)` with digest
  `cecc8aa8a16de673292c5bda6e96fab070080592ead3fb82fd1e40286c3172db` and
  `[6861029, 6861030)` with digest
  `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`.
- A clean temporary replay directory was populated only from the retained ZIP,
  normalized filing, and extension schema. The pinned offline parser replayed
  both normalized and canonical filings. Both produced 1,856 facts and semantic
  digest
  `c1a098e547276a804299bd16e387f5d1967696b34a66786cc429e6815850361d`, with
  engines `sec-efm` and `dqc-us`, no blocking findings, and zero network
  attempts. Validation evidence was `strict-sec-efm-profile-selected` and
  `dqc-dqcrt-checks-completed`; the profile digest was
  `639140b39584b3ee3276f09a011403dec911efe41ea1b98773f5f770bd5200d4`, matching
  the live manifest, and the taxonomy digest was
  `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`.
- The repeatable replay command (exit 0) uses
  `scripts/verify_issue312_sec_replay.py`. It recomputes source hashes, checks
  the normalization ranges and pinned profile digest, then compares facts from
  normalized bytes with facts from the SEC ZIP member:

  ```sh
  uv run --project fundamental-service python scripts/verify_issue312_sec_replay.py \
    --evidence-dir /private/tmp/issue312-retained-evidence-4fe205a3/objects \
    --edgar-plugin-dir /private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
    --xule-plugin-dir /private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
    --dqc-ruleset-path /private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
    --taxonomy-cache-dir /private/tmp/issue312-sec-taxonomy-2023-2024
  ```

  It returned 1,856 facts, profile digest
  `639140b39584b3ee3276f09a011403dec911efe41ea1b98773f5f770bd5200d4`, and
  semantic digest
  `c1a098e547276a804299bd16e387f5d1967696b34a66786cc429e6815850361d`.
  `uvx --from ruff==0.14.14 ruff check --select E,F,I scripts/verify_issue312_sec_replay.py`
  and the matching `ruff format --check` both exited 0.
- `uv run --project fundamental-service ruff check fundamental-service/src fundamental-service/tests`
  was attempted but exited 2 because the `ruff` executable is absent from that
  project environment; Ruff 0.14.14 passed the changed-file `E,F,I` and format
  checks after the style checkpoint. Load/soak and deployment rollout checks
  remain intentionally unrun. These results do not complete all #312
  acceptance criteria or resolve the blocker label. Next: inspect the full
  issue branch diff against every #312 criterion, obtain an independent
  read-only review, run any affected checks, then open the main-based PR and
  collect its exact-head CI.

## Acquisition-role compatibility and exact-SHA verification

- Implementation checkpoint: `9f74b67493d7272f1d9e1c8b829ab7d0079f5175`
  (`fix(fundamental): classify SEC acquisition evidence Refs #312`). The
  change gives SEC submissions an explicit `SourceRole.ACQUISITION`, keeps the
  lookup response in immutable snapshot and audit evidence, and excludes that
  role from point-in-time coverage and source selection. Historical manifests
  retain read compatibility for the removed field and for old digest and
  capture-time representations; a manifest with a verified capture-time
  contradiction still fails closed. No stored record or PostgreSQL volume was
  rewritten.
- Focused checkpoint command (exit 0):
  `uv run --project fundamental-service pytest fundamental-service/tests/test_snapshots.py fundamental-service/tests/test_source_acquisition.py fundamental-service/tests/test_sec_source.py -q`
  Result: `24 passed, 1 warning`. Changed-file Ruff `E,F,I`, Ruff format, and
  `git diff --check` all exited 0. Commit hooks passed.
- Exact-SHA service command (exit 0):
  `FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18481/fundamental_test_9f74b674 ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip ISSUE312_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 fundamental-service/.venv/bin/pytest -q fundamental-service/tests`
  Result: `197 passed, 2 warnings`, no skips. The Agent client suite returned
  `4 passed`; architecture guard reported no boundary violations; and
  `uv lock --check --project fundamental-service` exited 0.
- PostgreSQL focused exact-SHA checks returned `5 passed, 1 warning`, covering
  50-process coalescing, distinct-key lock isolation, terminated-owner lock
  recovery, atomic publication rollback/recovery, and authorization audit.
- Retained-evidence replay exited 0 with 1,856 facts, semantic digest
  `c1a098e547276a804299bd16e387f5d1967696b34a66786cc429e6815850361d`, pinned
  validation profile digest
  `639140b39584b3ee3276f09a011403dec911efe41ea1b98773f5f770bd5200d4`,
  taxonomy cache hash
  `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3`, and
  zero network attempts. Both normalized and canonical filing replay paths
  had no blocking findings.
- Docker project `value-investment-agent-issue-312-sec-ingestion` used only
  `fundamental-postgres` and `fundamental-service`, with PostgreSQL `18481`
  and service `18082`. The rebuilt service image is
  `sha256:7afd22674ebd6180106ad0a6e509f7896cdaf4ca2eae084834ff8baf3e92c934`;
  both services are healthy and `/readyz` returns
  `{"status":"ready","contract_version":"internal.v1"}`. Runtime plugin
  hashes are EDGAR `054a21fa824797787acc2c6e98af4bb040c51bbee41b613cee1793db8fd144af`
  and Xule `63123d67048019e3c49a0efde0e0aa8ec3eba0fc971da56ebd96dea8e40cd713`.
- Authenticated live Microsoft ingestion on the rebuilt image returned HTTP
  200 `created`, `quality_status=verified`, 57 fact IDs, snapshot
  `snapshot-26fe4569b08f4c8b87c916ac6387ae43`, and manifest digest
  `c96882aaefc5836b9d6d37e32dbe6ea6e126a6643e019a4d124cc2405e68fc65`.
  The persisted `sec-submissions` source has role `acquisition`, while the
  selected filing, index, archive, and taxonomy remain available with their
  historical timestamps. A retry and the Agent typed client both returned
  `reused=true` with the same snapshot, manifest, and 57 fact references.
  PostgreSQL audit outcomes are `created` and `reused`, each with five source
  hashes.
- The independent read-only review's P2 finding about current submissions
  metadata downgrading historical snapshots is resolved by this checkpoint.
  Load/soak testing and deployment rollout remain intentionally unrun; no PR
  has been created and issue #312 remains open with its `blocker` label until
  final diff review and exact-head CI.

## SEC redirect rejection and exact-head checkpoint

- Issue: #312. PR: [#332](https://github.com/sosodennis/value-investment-agent/pull/332),
  base `main`. Candidate head:
  `4749fd7ff9f2ed02e7283d9c7896fb904e34d406`. Candidate base is
  `origin/main` at `10a88e41f3f5d63ec9feebb472dbd4d5469c647f`.
- Issue-scoped code checkpoints:
  `658042a4cd01e392687cf0252d08a5d98d020fc1`
  (`fix(fundamental): reject SEC source redirects Refs #312`) disables
  urllib's automatic redirect handling and maps redirect responses to the
  non-retryable `SOURCE_REDIRECT_NOT_ALLOWED` error;
  `4749fd7ff9f2ed02e7283d9c7896fb904e34d406`
  (`test(fundamental): verify SEC transport blocks redirects Refs #312`) adds
  a real loopback HTTP 302 regression test proving the redirect destination
  receives zero requests. The adapter test also confirms the stable error and
  that only the allowlisted SEC URL is requested.
- Read-only reviewer re-reviewed exact head `4749fd7f` and confirmed the
  redirect/SSRF finding is resolved: production construction uses the
  protected default transport, redirects become `SOURCE_REDIRECT_NOT_ALLOWED`,
  and the loopback test observes zero destination requests. No other actionable
  findings were reported. The reviewer made no changes and ran no tests.
- Exact-head local verification reported for `4749fd7f`:
  - Fundamental service suite: `199 passed, 2 warnings`, no skips.
  - SEC source tests: `10 passed`.
  - PostgreSQL coalescing, distinct-key, process-recovery, publication-recovery,
    and authorization-audit checks: `5 passed`.
  - Agent client suite: `4 passed`.
  - Architecture Guard, dependency lock check, Ruff, format check, and
    `git diff --check`: passed.
  - Retained SEC replay: 1,856 facts; semantic digest
    `c1a098e547276a804299bd16e387f5d1967696b34a66786cc429e6815850361d`;
    zero network attempts.
- Docker project `value-investment-agent-issue-312-sec-ingestion` remained
  healthy with its existing PostgreSQL volume and database. The candidate
  service image was
  `sha256:1eadf3b8e88e8e0daa10c01353f1b72a909ba70782d0ac7301ebbe4140e70d0a`;
  `/readyz` returned ready. Signed live ingestion returned `created`, verified,
  with 57 facts and snapshot `snapshot-fe49c6730def13de896ac29fb99421f2`;
  manifest digest was
  `c6003e981afa14dc7cc0beff1c078952aeb22394254bcf380b09b4d53b4bc57d`.
  A retry reused the same snapshot and digest. The submissions source had role
  `acquisition`.
- GitHub state at this checkpoint: PR #332 still points to the older head
  `ce286b3c8d613fdf5e96f1903230c5c6952ad2bc`; its checks passed, with
  `fundamental-release-gate` skipped. Those checks do not verify `4749fd7f`.
  Issue #312 remains open with its `blocker` label. This checkpoint is not an
  acceptance or `VERIFIED` record. Next: commit this evidence, push the code and
  evidence commits, update PR #332 with the candidate head and evidence, then
  require CI and final acceptance against the new exact PR head before merge.
