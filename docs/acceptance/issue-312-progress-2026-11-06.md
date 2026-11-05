# Issue 312 progress checkpoint

This is an engineering progress record for issue #312. It is not an
acceptance or VERIFIED record.

## Checkpoint

- Branch: `codex/issue-312-sec-ingestion`
- Worktree: `../value-investment-agent-issue-312-sec-ingestion`
- Base: `origin/main` at `bee63cb37da9edb2deb444e14d2fc666aed73d06`
- Prior implementation checkpoints: `48cbf3067cf1872b632e5020a8e6263e4d636929`,
  `6422a7cd`, `4adb1b9f`
- Current checkpoint: WIP parser plugin initialization; no acceptance commit yet
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

- Command: `uv run --project fundamental-service pytest fundamental-service/tests/test_arelle_parser.py -q`
- Result: exit 0, 7 passed.
- The service parser was run against the same Apple filing with the pinned SEC,
  Xule, and DQC resources and with `socket.socket.connect` replaced by a
  function that raises on any network connection. The parser rejected the run
  with `DQC_VALIDATION_UNAVAILABLE`; this is a failed acceptance probe, not a
  successful offline EFM/DQC validation.
- Arelle initializes its `DisclosureSystem.Types` hook cache before the SEC
  plugin is dynamically registered. Clearing that cache after registering SEC
  and DQC plugins makes the strict SEC profile select successfully and sets
  `EFMplugin=true`.
- The remaining integration failure is that direct library validation does not
  initialize the SEC command-line filing context expected by the EDGAR filing
  validator. Xule/DQC execution has not yet been proven through the service
  parser. Do not treat the focused parser tests or profile selection as DQC
  acceptance.

## Remaining verification

- Capture and verify the complete taxonomy manifest and directory digest used
  by the service profile.
- Initialize the required SEC filing lifecycle in the service-owned parser,
  then rerun the same filing with network access denied and record the command
  exit code and EFM/DQC findings.
- Run the issue #312 contract, authentication, PostgreSQL concurrency,
  fault-injection, replay, Docker health, and Agent client checks against one
  exact commit.
- Record any expected filing-level EFM findings according to the service's
  quality policy before deciding whether the result is `degraded`, `abstain`, or
  publishable.
