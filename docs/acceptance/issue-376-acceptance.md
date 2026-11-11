# Issue 376 diagnostic checkpoint

Status: partial research evidence; empirical study incomplete. No threshold,
mapping, policy, release or valuation quality is approved by this checkpoint.
Refs #376; protocol blocker #377; historical owners #369 and #371.

Implementation tested: `6323686e69594a804e61111cba12fe608c3f74cc` on
`codex/issue-376-history-study`, based on main
`52e84dfe5a0dae0c11d2e62fd9a58e885b6eadc9`.
Worktree:
`/Users/denniswong/.codex/worktrees/issue-376-history-study/value-investment-agent`.
Later acceptance documentation does not change the tested implementation.

## Exact-commit evidence

The clean-worktree checkpoint executor ran every command at the implementation
commit and checked HEAD and clean status again at completion. Its external
canonical receipt records every argv, exit code, log digest, input/output digest
and full audit summary.

| Artifact | SHA-256 |
| --- | --- |
| Checkpoint receipt | `a823ed38967f293bb69e9459b5bab86bf35fccfa1b1f6f93796605fcd6cd8f5c` |
| Checkpoint inputs | `456835af248f598df8cc331a3eee6c7bdc75c4815987d4bfacda02f687aca1e5` |
| Checkpoint outputs | `c244d91169db162d083cafab2003e03b958dc11ff710fbe26501fe56c2adcfea` |
| DQC audit report | `11464789ae9b2e547c7761f31f46cbed54f8392675cda91b11c493cf7f16acaf` |
| DQC inputs | `daa0f23e24b39675980efa6d26fade01f558f52c24342a311766ee4a1f029cbb` |
| DQC outputs | `198d3e8953d780a02ba68da0929364659a1c13855002629ad9ea08493a2a4898` |
| Source representation report | `75353eb582b53d88564ab694d3955b55e76aea60548a85c357556e16611bdaa5` |
| Source inputs | `73142268bc6c0fac7343b4ed902eb458d178bb229e73b3f3f2d4ac8b78a27090` |
| Source outputs | `56ac004cdde72c180d0d4d625da742bb53f023940ad65808de46b6e5adbe684e` |
| Fundamental lockfile | `57b9ea3f92002720d4bce735df3316df071479da4c0599a31ae914e9e6c32a18` |
| Checkpoint executor | `643afb547ebcedeedc4f994a812ffdd79bf4c67203bc4b52ff748b1ef3f3fc7b` |

Runtime: CPython 3.11.15, lxml 6.1.3.0, libxml2 2.14.6. These audit runtime pins
are distinct from the historical parser's recorded runtime; original results
and their original pins remain unchanged.

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence`.
Reports and command logs are under `checkpoint-6323686e/`; official references
and exact executor sources are under `references/`. The original research tar,
manifest and complete-history bundle remain in the separately verified #361
research archive. Local retention is not a shared production evidence service.

## Executed checks

All commands exited 0 at the exact implementation commit:

- `uv run --frozen --project fundamental-service pytest scripts/tests/test_audit_history_dqc_applicability.py scripts/tests/test_audit_history_source_integrity.py scripts/tests/test_verify_issue361_research_archive.py -q`: 21 passed, no skips.
- Ruff 0.14.14 `check` and `format --check` on the three tools and three tests.
- mypy 1.15.0 `--follow-imports=skip --ignore-missing-imports` on the three tools.
- `python3 scripts/architecture_guard.py --summary`.
- `uv run --frozen --project fundamental-service python -m fundamental_service.architecture_guard`.
- `git diff --check`.
- Complete archive verification/reuse: 10,358 files; `wrote=false`; every
  existing size and mtime unchanged after content verification.
- Complete 589-filing DQC audit, then identical repeat: same input/output/report
  digests, `wrote=false`, zero new report files and unchanged bytes/sizes/mtimes.
- Complete 187-filing source-representation audit, then identical repeat:
  same input/output/report digests, `wrote=false`, zero new report files and
  unchanged bytes/sizes/mtimes.

The exact checkpoint driver command was
`uv run --frozen --project fundamental-service python /tmp/issue376-verify-checkpoint.py`.
The external receipt retains its complete subprocess command arrays. The
[runbook](../research/history-sufficiency-study.md) provides the parameterized
reproduction commands. Both full audits read local retained bytes only; no new
SEC download, database publication or composer invocation occurred.

## Observed limits

The fixed population remains 100 issuers and 589 filings. Ninety-five parser
refusals have only pre-effective blocking DQC findings; none were relabeled as
passed. Of 187 size refusals, 55 have equal Canonical XML without comments and
132 differ. Canonical equality is not regulatory or financial approval.

Nine missing first-original labels and one horizon mismatch cap complete
eligible pairs at 90. The original hardcoded 100-complete-pair state and
descriptive history groups require #377's reviewed accuracy/power protocol.
The official Hyndman sources informed the proposed evaluation method only;
they supply no financial labels or threshold ground truth.

No service runtime or browser workflow changed. Docker/service-backed empirical
acceptance, formal #352 forecasts, reviewed mappings/policies, complete labels
and the full forecast replay repeat have **not** passed. The study remains
incomplete with `supported_history_threshold=null`; #376 must stay open.

## Official assertion and historical parser checkpoints

The next two issue-scoped implementation commits preserve the original
evidence and modern defaults while repairing historical validation tooling:

| Increment | Exact implementation commit |
| --- | --- |
| Official Arelle assertion replay | `33053708d3ee461799d1134634077f84aaddf57c` |
| Pinned historical parser boundary | `c4c8a352b86f481e9f829716326941587e848a17` |

The corresponding external evidence is under `checkpoint-33053708/` and
`checkpoint-c4c8a352/` in the same evidence root. Every checkpoint receipt binds
the exact clean commit, executor source, lockfile, inputs, outputs, complete
command arrays, exit codes and command-log digests. The executor sources are
`references/issue376-conformance-checkpoint.py` and
`references/issue376-parser-checkpoint.py`. Both assert unchanged HEAD and clean
status at completion. These are host/offline parser checks; no new Compose,
database publication or forecast invocation occurred.

| Artifact | SHA-256 |
| --- | --- |
| Assertion checkpoint receipt | `e55f9167e3d7c2fccc4c4adb11f364933e6492fa121c60f5c609ee6b6429086f` |
| Assertion checkpoint inputs | `64991f93ab5856aa479799ba7c57b72470bb070d4e256a588609adcff144b8a8` |
| Assertion checkpoint outputs | `b1e38eac97e3e529ff3bda141bcd719dad8895bef37293c74dca2000d02d6363` |
| Full assertion report | `192a2758c5cf700c3e0b60841f82f5f5a2308484bf700828ce3e7c7b43c64c28` |
| Full assertion inputs | `f953c5c320a5d31f543f2736688ef77e852d7ea0635d2331e15a247ce5a5554f` |
| Full assertion outputs | `1527bfef5f4e7fc493d95c680f4d78ec4dee03af23d7c11ef53602dc574deef4` |
| Parser checkpoint receipt | `405926ff211280ece62590fbf55896ba848793dd05e808c5285df599efdc7f5d` |
| Parser checkpoint inputs | `273add3c12a6134d2c45ebe20b13c5a8724020d620551de206fdb5189e18612c` |
| Parser checkpoint outputs | `54a58d085277922303480ffa9f23c481fcb4324a65b5540ae1ce3f37b486bded` |
| Original parser report, DQC v1 | `f3254b1597573891f7087917acba4e1a5775944ec4400f36f1e6ca64b2915e0b` |
| Original parser report, DQC v3 | `67ad1a82a67dc2222e7f35476eb5a13a7f0b71521a4c27970cd618ea655cdc8e` |

The complete assertion replay verifies the official suite ZIP, original input,
all four pinned shards and all 6,586 case records. Official assertion matching
and completed execution agree for 6,585 cases. Nine cases previously failed
only because the bespoke runner demanded equality of all findings. The
remaining `DQC_0001.57.2612` uses unsupported US GAAP 2011 and remains failed.
Extra findings, original statuses and severities stay traceable by digest.
This re-evaluates retained execution, rather than freshly running all rules.
The second complete assertion replay returned `wrote=false`, matching all
digests with zero new reports and unchanged bytes, sizes and mtimes.

At the parser commit, the complete Fundamental suite passed 322 tests with 27
explicit resource/database skips and one existing serializer warning. The
research tools passed 34 tests without skips. The configured real-original
historical boundary tests passed 19 tests without skips. Focused Ruff/format,
mypy, both architecture guards and `git diff --check` all exited 0.

The real-original test uses CIK 0001539778 / accession
0001477932-16-007985. Both historical profiles independently execute, extract
327 facts and repeat with identical semantic digests. Each generated original
parser report was then repeated at the exact commit: `wrote=false`, matching
input/output/report digests and unchanged bytes/sizes/mtimes. All source,
taxonomy and plugin hashes remained unchanged. The tests reject changed rule
packages, incorrect source hashes and unsupported modern historical validation,
and retain diagnostic findings across the worker boundary.

Blocking negative-PPE finding `DQC.US.0015.2098` survives EDGAR's releveling to
warning. The current ingestion gate still rejects the unreviewed historical
completion marker. No mapping/release/publication or history threshold is
approved. Full cohort source integration, historical applicability/release
review, issuer/period mappings, market policies, #377 protocol and formal #352
forecasts/labels plus service-backed repeat remain unfinished. Next: resolve
the versioned source/validation contract and verify its full fixed inventory;
keep every refusal and the threshold null.

## Source character-delta diagnostic and CI

At clean documentation HEAD `f5bee8396ad2c34168117cbee4f4b62f55568bcc`, an
external diagnostic compared all 132 Canonical-XML-different direct/archive
pairs using their hash-checked retained sources. The script is preserved at
`references/issue376-source-delta-probe.py`; its source digest, dependency
source digests, lockfile and runtime pins are bound in the report inputs.
It compares parsed element order, names, namespace maps and attributes, then
classifies character-data differences without modifying either source.

All 132 retain the same compared structure/attributes/namespaces. Fifty-eight
differ only by spaces/tabs on otherwise empty lines. The other 74 have other
XML whitespace differences. No pair changes character content after erasing
XML whitespace, and none changes the text of a fact carrying `unitRef`.
Whitespace remains XML character data; this diagnostic neither establishes
complete XBRL semantic equivalence nor approves blanket whitespace stripping,
source publication, financial materiality or mappings.

| Artifact | SHA-256 |
| --- | --- |
| Character-delta report | `d92a3543abe63419d3454255b204e33f96049dec0600b498d400cb71b86fef9b` |
| Character-delta inputs | `10dc4759909a0918db2777a73400f418f68b50347b20e2e791987f6730b4d9da` |
| Character-delta outputs | `9baafea780af75bf1b593b83110879f0ed0ec84182ac05b6763a369892150de7` |
| Repeat command receipt | `d77886fec8ecc5c9e109cf97310f36e5e525a1c69405a23595155a580ca5196f` |
| Repeat receipt inputs | `d2d8dc1dc5a921a3b99c012e4793edbb5d9224b6ebc8cfd6e8c639372c5261e6` |
| Repeat receipt outputs | `5e8631b4b3e28fc5f09b1c4e98cbd82070c1f9d6a66e575ed99e44f58edfc881` |

Run with `uv run --frozen --project fundamental-service python` followed by the
external probe path above. `references/issue376-source-delta-repeat.py` records
the complete command, exit 0 and log digest; repeat returned `wrote=false`
without new probe artifacts or changed existing bytes/sizes/mtimes. Reports
are under `source-delta-probe/` and `source-delta-repeat/` outside Git.

This supports reviewing the premise that the indexed SEC direct XML must
byte-match its separately indexed ZIP member. A versioned source contract
should identify the selected authority, retain both original representations
and discrepancies, verify each object's own index size/hash/receipt and require
the selected parser/financial evidence checks. It must not claim byte identity
or erase text differences. That source contract is still unimplemented and
unapproved; original size refusals remain retained.

GitHub checks at `f5bee8396ad2c34168117cbee4f4b62f55568bcc`: all 12 executed
checks passed, including `offline-research-contracts`; the separate
`fundamental-release-gate` was skipped. The saved status receipt is
`checkpoint-c4c8a352/github-ci-f5bee839.json`. PR #378 remains draft; CI success
does not replace historical release review or the empirical forecast study.
