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
