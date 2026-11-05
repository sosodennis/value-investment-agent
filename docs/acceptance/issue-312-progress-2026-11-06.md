# Issue 312 progress checkpoint

This is an engineering progress record for issue #312. It is not an
acceptance or VERIFIED record.

## Checkpoint

- Branch: `codex/issue-312-sec-ingestion`
- Worktree: `../value-investment-agent-issue-312-sec-ingestion`
- Base: `origin/main` at `bee63cb37da9edb2deb444e14d2fc666aed73d06`
- Implementation checkpoint: `48cbf3067cf1872b632e5020a8e6263e4d636929`
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

## Remaining verification

- Capture and verify the complete taxonomy manifest and directory digest used
  by the service profile.
- Run the same filing through the service-owned offline parser with network
  access denied and record the command exit code.
- Run the issue #312 contract, authentication, PostgreSQL concurrency,
  fault-injection, replay, Docker health, and Agent client checks against one
  exact commit.
- Record any expected filing-level EFM findings according to the service's
  quality policy before deciding whether the result is `degraded`, `abstain`, or
  publishable.
