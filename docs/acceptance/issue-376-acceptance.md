# Issue 376 diagnostic checkpoint

Status: partial research evidence; empirical study incomplete. No threshold,
mapping, policy, release or valuation quality is approved by this checkpoint.
Refs #376; protocol blocker #377; historical owners #369 and #371.

Initial implementation tested: `6323686e69594a804e61111cba12fe608c3f74cc` on
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
or erase text differences. At that checkpoint the source contract was
unimplemented and unapproved; original size refusals remain retained. The next
increment implements an internal research selector without approving publication.

GitHub checks at `f5bee8396ad2c34168117cbee4f4b62f55568bcc`: all 12 executed
checks passed, including `offline-research-contracts`; the separate
`fundamental-release-gate` was skipped. The saved status receipt is
`checkpoint-c4c8a352/github-ci-f5bee839.json`. PR #378 remains draft; CI success
does not replace historical release review or the empirical forecast study.

## Accession archive implementation and complete subset execution

Exact implementation: `fb4c983a3428a3141936ff02a1c72f7214bb0df2`.
Fundamental Service now owns the internal
`historical-archive-selection.v1` / `sec-original-xbrl-archive-v1` research
contract and the shared bounded ZIP reader. It binds the frozen filing metadata,
each object's own indexed length and unchanged member/source hashes; it retains
both representations and discrepancies. The audit reports the archived missing
HTTP receipts as null, never as invented HTTP 200. It binds supplied acceptance
metadata without independently certifying original/amendment history. Existing
production exact/Akamai integrity and publication policy remain in force.

At that exact clean commit, the complete Fundamental suite passed **357 tests**
with 27 explicit resource/database skips and one existing serializer warning.
The five research test files passed **36 tests** without skips. Ruff 0.14.14
check/format, mypy 1.15.0, both architecture guards and `git diff --check` all
exited 0. The checkpoint receipt records complete command arrays and log hashes.
Runtime: CPython 3.11.15, Arelle 2.47.4, lxml 6.1.3, Pydantic 2.14.2; the locked
dependencies, exact parser profile, plugin resources and taxonomy cache are
bound in the inputs and verified unchanged after execution.

All 187 original source-size-refusal rows remain in the selected subset, spanning
61 independent issuers within the fixed 100-issuer / 589-filing population.
The selection audit chose 180 original ZIPs for validation and retained seven
10-K/A refusals under the original-only policy. The complete selection repeat
returned identical digests and `wrote=false`, with unchanged bytes/sizes/mtimes.
No issuer or filing was substituted.

All 180 selected originals then received **fresh offline parser execution** with
strict EFM and the pinned historical DQC v3.6.2 profile:

| Outcome | Filings | Decision | History | Label |
| --- | ---: | ---: | ---: | ---: |
| Parsed without blocking findings | 26 | 10 | 11 | 5 |
| Parsed with retained blocking findings | 134 | 24 | 100 | 10 |
| Unsupported taxonomy refusal | 20 | 0 | 20 | 0 |
| Original-only selection refusal | 7 | 0 | 7 | 0 |

The 160 parsed filings yield 278,767 facts. All 20 taxonomy refusals use US GAAP
2011; these are unresolved, not passed through a newer-rule fallback. Findings,
original severities, fact identities, failures and every target remain retained.
These outcome counts describe the subset only, not 160 approved filings or
completed forecasts. No rule revision is certified historically applicable by
its execution in this profile.

The complete second pass rehashed **559 unique retained source objects**, then
reused all **180 parser result artifacts** with zero newly written results.
Its report returned `wrote=false` and the same input/output/report digests;
all existing corpus bytes, sizes and mtimes remained unchanged. This verifies
complete deterministic artifact reuse after source reverification. It is
**not** a second fresh execution of all 180 parser workers and is not the
unexecuted full forecast replay.

Two canaries were selected prospectively by minimum direct byte length among
original Canonical-XML-different targets within decision/history roles, with a
canonical target tie-break. Both direct and archive representations were freshly
parsed twice per canary; no favorable case replacement was made:

- CIK 0001269190, accession 0001193125-16-519551: 678 facts per representation;
  equal numeric fact multisets; a differing text-block group remains retained.
  `EFM.6.11.05` remains blocking for two monetary extension concepts without
  adequate sign-disambiguating documentation labels under the pinned EDGAR rule.
- CIK 0001107280, accession 0001273511-13-000018: 298 facts per representation;
  equal numeric fact multisets; two differing text-block groups remain retained;
  neither representation has blocking findings under the selected profile.

Both canaries have different complete fact semantic digests across their source
representations. Numeric agreement does not establish full equivalence or grant
mapping, materiality or publication approval. Repeated canonical parser reports
returned `wrote=false` and unchanged bytes/sizes/mtimes after fresh execution.

The official family-date diagnostic was also applied to all new subset results,
including findings retained in parser failures. Of 134 blocked parsed filings,
84 have only pre-effective DQC blockers: 12 decisions and 72 history filings.
The other 50 retain non-DQC or other applicability review. Every original status
and severity remains unchanged. Family dates do not resolve the exact revision,
historical EFM applicability or financial materiality. The diagnostic's repeated
canonical report returned `wrote=false` with unchanged bytes/sizes/mtimes.

All evidence below is outside Git under `checkpoint-fb4c983a/` in the existing
external evidence root. The executor sources are retained under `references/`.

| Artifact | SHA-256 |
| --- | --- |
| Checkpoint receipt | `f149888f62bda2ba0a639d84692ae5edd89659471e6d5359d01dae2b6ec61576` |
| Checkpoint inputs | `f411df67e9329c12ac22f112542d625a7ac01021fd97fede0ba53cfbb0dbd09a` |
| Checkpoint outputs | `9395a70a085dd56365f04e871299dad2f323027c9f0cc782c4a9cf1b30a1db18` |
| Selection report | `bca60230eabdaa335b2481e3cfac18bad8b72c39b982b9baf0656c34d3fcd850` |
| Selection inputs | `f010156dff840070032f5be20b5e4cb641e4f47279ab1d3c193db6fb96f3094b` |
| Selection outputs | `c8c17bd12fa054771a37122e66e375765d71997c65780e897bbdcc5b63079047` |
| Complete subset parser report | `b72ee05062541e45b9122b5c49b45e327b210ccd4f93f3d950df21b725fa1857` |
| Complete subset parser inputs | `5605c14c0ff9c878c8fdff1508dadaa9ad60642d2f56eddfb4fd7cea8ed1ae51` |
| Complete subset parser outputs | `918da2b55e4671c10f9bf3ff104d7c09a3fddc0ab144e9164526f7c97ffb9eb6` |
| Complete subset repeat receipt | `2ba93273ec9765d8debc6eb7e0631913e2b2ddef235dd9cc2ff0e45d473c049e` |
| Complete subset repeat inputs | `204cef59981655af2df384545e0d9dd6288245d11b7084ae2c3d1fd702fa93f4` |
| Complete subset repeat outputs | `3a1a9ba8703d931a1884a2603abada433dd3ef21756f17a42ab46bcfe078036e` |
| Pinned canary fact-delta report | `fb83b0f8b8eb6ed71e2852829229d905f3d9107f138f364bb047656f1a0c642d` |
| Pinned canary fact-delta inputs | `d117a97e06021960b7d4992a589e9ef71e39293f688954c876a0a6c63814f0ff` |
| Pinned canary fact-delta outputs | `50df59193d064be341af99cef61eb4e45326919119c56b5d5b9d1f83020eb7cc` |
| Subset applicability report | `37133f2e1b33b132d94df590f8520572efeecc30ddf32e24e5c6dbd57e92065f` |
| Subset applicability inputs | `176b031254a57f60982b458dd8c0aba1daaf699a9de0f9ee86d801d1bcaf8746` |
| Subset applicability outputs | `7dcae8bbce79485ad5f84e9282422ef2b2b7627c779cf1977d3aba36c618403c` |

Execute each driver using `uv run --frozen --project fundamental-service python`
followed by the absolute external `references/` path. In order, the driver names
are `issue376-archive-checkpoint.py`, `issue376-archive-fact-delta.py`,
`issue376-archive-corpus-parser.py`, `issue376-archive-corpus-repeat.py` and
`issue376-archive-corpus-applicability.py`. All exited 0 at the exact clean
implementation commit; first corpus stdout is `corpus-parser-first.log`, repeat
receipt stdout is `corpus-repeat.log`, and applicability stdout is
`corpus-applicability-first.log`. The repeat receipt records exact argv, exit,
executor/log hashes and reverified source hashes. The corpus and applicability
reports bind their driver hashes, complete inputs and owning classifier pins.

All 12 executed GitHub checks passed at the implementation commit; the separate
`fundamental-release-gate` was skipped. Saved status:
`checkpoint-fb4c983a/github-ci-fb4c983a.json`. Documentation added after these
checks does not change the tested code or replace empirical acceptance.

### Remaining work and next delivery

The [FASB accounting-era evidence](../research/history-sufficiency-study.md#accounting-era-mapping-evidence)
adds linked blocker #380: unconditional modern lease and contract-asset roles
do not establish the correct 2016 input representation. Review issuer/period
original adoption/disclosures and implement versioned applicability in owning
Fundamental contracts. Do not invent zeros, equate commitments with recognized
liabilities, double-count receivables or leak later restatements.

Next: resolve #371 historical applicability/materiality and release integration,
US GAAP 2011 and amendment/receipt limitations, #380 accounting-era roles,
issuer/period semantic review, #369 historical market-policy review and trusted
releases. Freeze #377's error/power and within-issuer history comparison protocol
before threshold selection. Then execute formal #352 forecasts/labels and the
isolated service-backed complete replay/repeat. No Docker resources were created
or changed by this increment. The original 100 issuers remain fixed; nine missing
labels and one horizon mismatch remain in the denominator. **Canonical study
forecasts remain zero, supported_history_threshold remains null, and #376 / PR
#378 remain open/draft.** This is completed engineering evidence, not a completed
empirical study or an approved underpowered forecast conclusion.

## Frozen first real case and source packet

The repository owner confirmed the delivery order now recorded in #376:
historical applicability/input semantics; one real forecast/label/error/repeat;
freeze #377 before threshold selection; expand to the unchanged fixed cohort.
Primary study progress remains **0/100** completed issuer forecast/error paths.

Exact implementation `6fcab170d82b5ff7aa14a61702099c39855fe1b3` adds
`scripts/audit_history_first_case.py` and its boundary tests. The frozen rule
sorts by original decision timestamp then issuer ID, selects a source-supported
original decision/history/first-label diagnostic packet and preserves every
ineligible issuer and reason. It binds the 187 updated targets only to original
source-size refusals and retains all original digests/statuses. This is an
overlay of retained batches, not a new full-589 parser run or model eligibility.

The full 100-issuer / 589-filing audit finds seven diagnostic cases. The first
is **CIK 0001282637 / NEWMARKET CORP**, origin **2016-02-12T16:26:17Z**.
Its selected source filings are:

| Role | Original accession | Facts | Fresh executions | Blocking findings |
| --- | --- | ---: | ---: | ---: |
| History | `0001282637-15-000004` | 1,687 | 2 | 0 |
| Decision | `0001282637-16-000028` | 1,485 | 2 | 0 |
| First subsequent annual label | `0001282637-17-000005` | 1,378 | 2 | 0 |

The complete original case inventory also retains its other refused history
filings. Discovering role gaps does not authorize selecting another issuer.
Each selected original was freshly parsed twice under the pinned strict EFM /
historical DQC v3.6.2 profile at the exact implementation. Both executions match,
and every full fact multiset matches its retained original. Parser sources,
resources and the independent taxonomy-cache hashes remain unchanged. The three
canonical parser artifacts and the full source packet repeat with `wrote=false`.
The later label's observations remain separate from origin observations.

The review packet reads current formal Fundamental requirements and queries
original parsed observations. The old CompanyFacts proposal supplies only
unapproved concept-name search hints, never numeric values. Six additional
source-observed concept hint groups remain explicitly unapproved. These include
combined basic/diluted-share tags, net receivables, legacy rent expense and
total/noncurrent debt; their existence does not establish complete/nonoverlapping
role coverage. The packet retains context, namespace, period, unit, dimensions,
scope, value, source hash, accession and exact parsed-fact digest for review.

It finds original consolidated numeric candidates for **19/32 FCFF roles**;
13 roles lack such candidates under these hints. This does not establish model
period completeness, exact amount/precision, accounting-era applicability or
semantic approval. Transition additionally requires its filed operating evidence,
which has not been adjudicated. **Zero roles and zero historical market policies
are approved** in this packet; no canonical facts, release or forecast is created.

A concrete disclosure narrows the owning #381 gap: the FY2015 original
`DisclosureOfCompensationRelatedCostsShareBasedPaymentsTextBlock` reports
recognized restricted-stock/RSU compensation expense for 2015, 2014 and 2013,
despite the absent directly matching numeric tag. The narrative receipt binds
the exact source fact/hash/context and source-view quote offsets. Missing numeric
tags cannot justify a zero. Those rounded, class-specific amounts also do not
automatically cover the full role. Source-bound numeric disclosure extraction,
currency/precision/class coverage and independent semantic review need the
owning Fundamental contract, recorded in
[#381](https://github.com/sosodennis/value-investment-agent/issues/381#issuecomment-6792426312).
No competing accounting API or alternative valuation formula was added here.

At the clean implementation, **48 research tests passed** with no skips;
focused Ruff 0.14.14 check/format, mypy 1.15.0, both architecture guards and diff
check exited 0. Tests cover stable selection independent of forecast outcomes,
all-case/failure retention, duplicate/foreign/changed overlays, frozen label
identity, future input and in-sample-label rejection, null selection, corruption
and unchanged artifact reuse. Production service code is unchanged by this
increment; its previously passed local suite was not redundantly rerun. All
12 executed implementation CI checks passed; the separate release gate skipped.

External evidence lives under `checkpoint-6fcab170/` in the same root. Run the
drivers using `uv run --frozen --project fundamental-service python` followed by
the external absolute `references/` path:
`issue376-first-case-checkpoint.py`, `issue376-first-case-source-packet.py`, and
`issue376-first-case-narrative-gap.py`. All exited 0 at the exact clean commit.
The first driver records full argv, exits and content-addressed command logs;
the source packet log is `source-packet-first.log`. Each report binds executor,
source reports, code/lock/runtime and applicable resource digests. Runtime remains
CPython 3.11.15 / Arelle 2.47.4 / lxml 6.1.3 / Pydantic 2.14.2. The full case
selection repeat has identical digests and unchanged bytes/sizes/mtimes. The
fresh source-parser repeats are distinct from selection-artifact reuse.

| Artifact | SHA-256 |
| --- | --- |
| Exact first-case checkpoint | `905a95fe0d8ead90a32c3ad0e9fc1e7f398a58cdbc3378146dee0346da64dd1a` |
| Checkpoint inputs | `659a606f68f374e08892549a53c6fec3f5f4a998861c72af7abf2dc95ef1260b` |
| Checkpoint outputs | `a645afb7138db2f7249afbd25a74ca30f0396e6e45913ec5b26c5a48aeacadb8` |
| Complete fixed-case selection | `1dde4561b08965b9abb12426f4a78548c066444ebcd3f4e997948c22e854fee0` |
| Selection inputs | `9b7fb752ca808c8ef8760236ab0f066465aea465fd8bf2fe0ca1581fd575d848` |
| Selection outputs | `22870d2ed909e62135f86d51c278e948b6e90e23e1088bbb36cea4e6eb4d6b77` |
| Original-source review packet | `1e256221adb0fc2a3faf83ff98f5fdca416004cafe261c634b74ab5e5dec7bf7` |
| Packet inputs | `87aaed87b04560c686763f26070803523096fd61f8aa36c16cd2c3329ba5a6eb` |
| Packet outputs | `f1c8a580297a229c5b80844c917ecf0b341a6a05bda0425ff2aab77dcf2ed56f` |
| Narrative gap receipt | `783f98dada98e9f2fc273adc5442fcd4ebe746d129530035f0c40c19e2b657e1` |
| Narrative inputs | `3bf10a5fd6850e025b86bd0ef1ce011bceeb94c599edfc6f20dcabc6564ada93` |
| Narrative outputs | `e75a012ac66f6a97339b31afa2a8f1918248851d891fc641cdb5c87b7c5f83c0` |

Next delivery remains this fixed issuer's reviewed role/adoption evidence,
historical policy and trusted source/mapping releases, using #361/#379/#381
owning contracts and #371 historical validation review. Then execute formal
#352 forecast, first-original label, error and full service-backed repeat. All
100 issuers and every failure remain in the study; these three filings were
already in the prior passing set and do not increase the aggregate pass count.
No parent checkout, DB or Docker resource changed. #376 / PR #378 remain
open/draft and supported_history_threshold remains null.

## Shared formal operating stage (#383)

Exact implementation: `e4b1eaf7181f36dee5796a56539824ad0efe9da0`.
The issue owner approved continuing toward a real case; the concrete design
and ownership boundaries were recorded in linked blocker #383 before editing.
The archived study's revenue/undiscounted-FCFF targets now have an explicit
internal Fundamental contract. Full valuation and research share the original
#352 forecast composition and operating recurrence. Full valuation still
requires all 32 accounting roles, market policy and the capital bridge. No
research/Agent/UI formula or dummy market/share assumption was introduced.
The distinct operating profile has twelve annual numeric dependencies and
retains transition filing evidence, existing three-period candidate minimum,
five-period window and growth/reinvestment policy. Successful output is always
provisional, with null supported threshold and no per-share/intrinsic value.

The low-level composer takes already authenticated canonical evidence. Like
its existing full-valuation counterpart, it does not authenticate a supplied
release digest. The real research boundary must still verify original source,
mapping, trusted semantic review/release and the first-original label. This
increment supplies no new release authority, signed review or canonical facts.
Operating accuracy cannot establish the complete valuation's accuracy; #377
must explicitly freeze that claim before outcomes select a threshold.

At the exact clean commit, the retained external executor
`references/issue376-operating-checkpoint.py` ran all of these with exit 0:

- `uv run --frozen --extra dev --project fundamental-service pytest -q fundamental-service/tests --tb=short`:
  **397 passed, 27 explicit resource/database skips**, one existing serializer warning.
- `uv run --frozen --extra dev --project fundamental-service pytest -q scripts/tests/test_audit_history_*.py scripts/tests/test_verify_issue361_research_archive.py --tb=short`:
  **48 passed, no skips**. The executor records expanded argv.
- Ruff 0.14.14 check for Fundamental; focused format for all five changed source
  modules plus `test_operating_forecast.py`; mypy 1.15.0
  `--follow-imports=skip --ignore-missing-imports` for the five changed modules.
- `python3 scripts/architecture_guard.py`;
  `uv run --frozen --project fundamental-service python -m fundamental_service.architecture_guard`;
  `git diff --check`.
- `uv run --frozen --project fundamental-service python` followed by external
  `references/issue376-full-valuation-parity.py`.

The 40 new tests cover both-model operating/full numeric parity, the six
pre-extraction preparation digests, required roles, wrong issuer/source/unit,
future facts/sources, missing history, dimensional and misaligned facts,
amendments, conflicting/duplicate IDs, tax/growth refusals, complete selected
and rejected evidence identity, versions, input order and independent Decimal
context. The output schema refuses verified quality or a supported threshold.
CI now covers these modules and keeps the full Fundamental suite.

Before extraction, six complete/blocked full-valuation cases were captured at
clean `824d2f6f`; their complete preparation/calculation output is **identical**
at `e4b1eaf7`, digest
`04f18826f52bcdaab01e8b7f88a68aa9239c42c2b2a4eff16009781b000563cc`.
The synthetic operating results for both models repeat canonically, and the
content-addressed report repeats with `wrote=false`, unchanged bytes/sizes/mtimes.
This is operating/synthetic parity acceptance, not empirical or Docker/service
acceptance of the fixed cohort. Runtime: CPython 3.11.15, Arelle 2.47.4,
Pydantic 2.14.2 and lxml 6.1.3; exact locks and executor/code hashes are in receipts.

All artifacts remain outside Git under `checkpoint-e4b1eaf7/` in the same evidence root:

| Artifact | SHA-256 |
| --- | --- |
| Exact checkpoint | `377cd60325ece2ad0bff55b10df1c242882137a37bc76703109d4ff7daf83d9e` |
| Checkpoint input | `3c29ee0685b9b6f80519bcba5088747d28c54f12af61135d3c1996653e202840` |
| Checkpoint output | `48ebe8d6f73aa489e45cbf8a86afebe5143620d1e9aad98cbab1d883212e25cf` |
| Operating report | `607fb9f14eb16b10cdb9ecc0a2678f85fea1e49723e506634b10bcc6a75be2bd` |
| Operating input | `5cdf1cb4670d1c0bcf9b6eb018e6f98096d8de69da137670547c670efcada3fe` |
| Operating output | `38711d54d06a675d5ecb9cf226c711ad87aec4e32c6e30f0063d9d50ebe7f1a9` |
| Full-valuation parity report | `0e9452b0a0bfc24e2ab72e8a8163be203d56e1b3b3404495f69ccdf5d47ba505` |
| Original full-valuation parity report | `7aff748b59058115585d890938a89c911b1b91c976264317fe48b01caa8382f3` |

The retained dependency probe at `824d2f6f` had eight synthetic cases across
both models: altered capital/share claims and discount/terminal growth leave
revenue/FCFF unchanged while affecting per-share value; the tax positive control
changes FCFF. Report
`89ea205cd4e6e848014b44bf6010410d8146f671ddc421b04db34906b5b40408`,
input `ace79fafd9b74de92b42a140482edf89c3190dc9c0f02fa6438d00b4a8aa6505`,
output `359d93022b7620338f62907f8788b5174b21e36b32dc3638e17dec1534ff102f`.
Two import attempts and a strict Python-vs-JSON validation attempt initially
failed; the corrected probe validates JSON at its actual boundary. The first
extraction test found a removed local-name reference, corrected before commit.
A broader mypy 1.19.1 follow-imports analysis does not pass the existing
optional/nonnumeric contracts; it is not the passing scoped CI type check.
Ruff 0.14.14 whole-suite formatting also flags the existing, unchanged
`test_release_runner.py`; only affected files were formatted/checked.

The architecture standard and all three project agent-skill entrypoints were
checked. No Agent graph/state/layer/import/runtime boundary changes here make
their existing guidance stale; no skill update or architecture exception is
needed. No parent checkout, DB, container, network or volume changed.

### Original operating-role review packet

At the same exact commit, external
`references/issue376-operating-source-review.py` exits 0 and preserves the same
NEWMARKET issuer/origin and original history/decision/first-label sources.
It verifies the existing source/parser/packet input and output digests, retains
all original observations, and separately organizes origin versus label facts.
It finds search candidates for **10/12 operating roles**, with **zero approved
roles**. `contract_assets` and `deferred_revenue` remain unknown; pre-Topic606
vocabulary or an unreported modern tag cannot establish economic absence.

The packet retains 46 component observations and 18 original disclosure views
with exact raw fact/context/unit/period/accession/source/parser hashes. The
FY2015 receivables table explicitly includes USD20.141m income-tax receivables
within USD287.967m trade-and-other receivables. Its accrued-expense table
includes USD13.927m capital-project payables within USD99.511m accrued expenses.
These are original disclosed components, not newly approved normalized roles.
Other receivables/accruals, allowance coverage and nonoverlapping classification
still require review; do not map either whole aggregate directly to operating
working capital or fill missing balances with zero.

| Artifact | SHA-256 |
| --- | --- |
| Source operating review report | `6ab2dc8e43e619935c2baf74f96196e1e59ee42d0b496f29d55e313b394ec46e` |
| Source review input | `e924f7e13f348d543ea96c7c85fc4da042053bb67e729d98fd2183fe7057efa0` |
| Source review output | `d5885f70fd90211dda6b382e14116b9123efb1a0396e34eba4db044314f940d2` |

Immediate repeat returns `wrote=false`, identical input/output/report digests,
unchanged existing bytes/sizes/mtimes, zero downloads and no canonical facts.
The full original sample stays 100 issuers/589 targets; this source packet does
not replace the first case or authorize promotion. Remaining work is actual
issuer/period/component/absence review and historical publication/release,
then #352 real forecast/first-original label/error, reviewed #377 protocol and
complete isolated service-backed repeat. Formal study completion remains
**0/100**, threshold null; #376/#383 stay open and #378 stays draft.

## Owning composer-v3 integration checkpoint

Exact implementation is ordinary merge
`8063d92d82233e57ddfe92f4ce32717d7769b80f` on the separate local branch
`codex/issue-376-composer-integration`. Its parents are research
`29321c8f97a0b8978a32fa194ce4ac9a1134b6b3` and owning #361
`071169f953e69713a5a202c9a0030356f1834802`. Both histories are retained.
The published #378 research branch and the main chat's checkout, branch,
database and Docker resources were not changed by this increment.

The shared operating stage now uses the owning `using_valuation_context`,
`fcff-forecast-composer-v3` and `decimal-50-end-of-year-v1`. Composer and
numerical-policy versions bind operating input/output identity. Both full
valuation and operating preparation use the same extracted assumptions and
operating recurrence. Parent historical parser identity, realized FCFF,
accounting-role contracts, typed checks and corrected operating-lease treatment
are retained. No forecast, tax, WACC or valuation formula was introduced in a
research tool. All successful operating outputs remain provisional; all
unresolved cases abstain and the supported threshold remains null.

At the exact clean implementation commit:

- Complete Fundamental tests: **693 passed, 48 explicit resource/database skips**.
- Research tools: **48 passed, no skips**.
- Scoped Ruff 0.14.10 check/format and mypy 1.19.1 with the CI import-following
  settings passed. Both architecture guards and `git diff --check` passed.
- Seven synthetic full-preparation/calculation cases match modules loaded
  independently from exact owning parent `071169f9`, including both complete
  models and blocked paths. These are compatibility fixtures, not empirical
  study forecasts. The complete and no-market goldens were migrated from the
  old composer baseline using this independent execution.
- Operating prepared/refused results reproduce under hostile Decimal traps,
  constrained exponents, reversed inputs and fresh worker threads, with caller
  state restored. The new owner version fields bind identity.
- Both operating model outputs and the parent-parity artifact were reexecuted;
  reused artifacts returned `wrote=false` with unchanged content, sizes and
  mtimes. No service-backed or Docker acceptance was claimed.

| Exact external artifact | SHA-256 |
| --- | --- |
| Engineering checkpoint | `f5c858ba73520ea7d1599795022afa659f5874d23eed5024c09c04ae58e28822` |
| Engineering inputs | `6d0069ae5b036c65e66b53b6353af83b8886e3fbf4b9945f82fca37577b493aa` |
| Engineering outputs | `1d556a63c4c7fd18e4b3f890b070d202963dc4753ea957d33e22e284b6d8a2c8` |
| Owning parent parity report | `884faef59582499c411400fb5324a68ff2a4847b16fc52b2f98864485fd4fdd9` |
| Parent parity inputs | `da8d9f41be1cb2a3a05725a82cd819bb59c360ffdbc9799820ffbeb5956d9545` |
| Parent parity outputs | `c30fb2fc280debe5f438f648ce140577a0ba573e5b15f50b58af3681847d14f9` |
| Integrated operating report | `31a3285bb12fc7523358d2d3ac40795dc782e25569de376a5da6fae1646465fb` |
| Operating inputs | `da5082fd1a370217fe356896e9dea833b4fa4d27efd64a152a6577d887004002` |
| Operating outputs | `ab920ccef50cd9b79a2c11e0b220d8ce8b2894a5cb8ff6410a3cf39a68f52d0a` |
| Source/repeat checkpoint | `cc50119eb0105bbf4f80a4562a0531ee74c1ffb173a121d560e4a180502e7f3b` |
| Source/repeat inputs | `8382bf168f812da0668f56ae8cc45c09e69eedd95304be95518461abf15f67e0` |
| Source/repeat outputs | `bfbb176d8b2910ab3e0feec46098d897632ab51dc5868d48f21162afbfe8e0b2` |
| Shared operating-stage patch against owning parent | `4b8b650adb8234852b5701c3d1cf2dd63a188a8624669fff2b750aa3331178e9` |

Evidence is under `checkpoint-8063d92d/` in the external evidence root.
`references/issue376-integration-checkpoint.py` retains all exact test/check
command arrays, exit codes, logs, runtime pins and source digests. The
independent comparator is `references/issue376-integrated-parent-parity.py`.
`references/issue376-integration-source-checkpoint.py` reexecutes the four
source/parity drivers twice each: eight successful commands, zero downloads,
zero new report/source artifacts, and 18 retained files with identical bytes,
sizes and mtimes. Command logs and the checkpoint receipt are distinct evidence
of execution; they are not study data identities.

## Fixed NEWMARKET mapping and historical identity evidence

The fixed case is unchanged: CIK **0001282637**, origin
**2016-02-12T16:26:17Z**, original history `0001282637-15-000004`, decision
`0001282637-16-000028`, first-original label `0001282637-17-000005`.
SEC official submissions acceptance times match all three frozen timestamps.
Only the original accession/filing/time fields are used for this audit; current
ticker and survival fields provide no identity or threshold authority.
The repeat makes zero network downloads and returns `wrote=false`.

The actual `CanonicalMappingV1` contract now validates **24 unapproved direct
mapping proposals**, covering eight roles across three originals and **66
annual source observations**. Each binds original accession, available-at,
parser/source/fact hashes, context, period, unit, scope, amendment state and
mapping version. All observations outside the declared annual/consolidated
scope remain in the excluded evidence. No numerical conflict occurs within
these proposed direct role-period groups. The first-original label proposals
are stored separately and never contribute to origin mapping inputs.

Four roles remain unresolved: operating current receivables, accrued operating
liabilities, contract assets and deferred revenue. The report validates **24
period-specific `AccountingPeriodRuleV1(disposition="unknown")` rules** without
numeric values or absence claims. Receivable aggregates contain income-tax
receivables; accrual aggregates contain capital-project payables. Other
components still need complete nonoverlapping classification. Missing modern
tags and revenue-recognition prose do not prove a zero balance. The report
creates no complete rule set with a placeholder security identity and invents
no missing HTTP receipt.

| Exact original evidence | Report SHA-256 | Output SHA-256 |
| --- | --- | --- |
| Official acceptance-time audit | `d1e48df4e9008680d412b552f2a97b16d9980712f582ec1f0c83dd3fbb60ed25` | `77473ebc95343da896ec0c03c7f844f02e175aa60105e2ba61e88c0911cf1851` |
| Typed mapping proposals | `21773660000382337295044fa3a00612469d1ba8ce5a7fed07b86a9e9d470001` | `32ac6480207f5c87a318a41b299f59ae8ac6ced5988afca07f9c01dbcd0bf6b1` |
| Original SEC cover acquisition failures | `69efb967a130a7051f7e9e4992cf9706d50e9b35aa8dfa962348faf78622d9f9` | `041e4dafe755caf0decdea7c8151918c4cde0aafc5e42d53707b19db17ba673f` |

The original reports also establish a separate source/identity gap:
all three complete original parser fact sets lack both `dei:TradingSymbol`
and `dei:Security12bTitle`. The current security-bound original-DEI policy
cannot authorize those sources. Exact original cover HTML retrieval returned
HTTP403 for all three accessions; complete status/body/hash receipts are
retained, never interpreted as filing content. Both successful acquisition
and retained403 outcomes repeat without downloads or artifact changes.

[Owning blocker #390](https://github.com/sosodennis/value-investment-agent/issues/390)
requires an explicit historical identity policy. First distinguish an
issuer-scoped operating claim from a security-bound per-share valuation. Any
issuer-scoped release contract needs owner-layer implementation and checks.
Alternatively, a security-bound original-cover policy needs actual retained
original bytes, exact class evidence, independent review and versioned source
validation. Current ticker data, a generated signature, an unchecked secondary
page or a caller bypass cannot establish the missing authority.

**Formal empirical forecasts remain 0/100, approved roles zero, canonical facts
published zero, threshold null.** The engineering integration and proposals
are concrete progress; they do not complete #376/#383. Next: resolve #390 at
the owner boundary while adjudicating the four fixed-case accounting roles,
then execute a genuine reviewed release-bound operating forecast, its isolated
first-original label, error and repeat. #377 still governs the prospective
accuracy/power/history comparison; preserve all100 issuers/589 targets and
failures. Main chat source improvements after `071169f9` are not implicitly
covered by this pinned integration evidence.
