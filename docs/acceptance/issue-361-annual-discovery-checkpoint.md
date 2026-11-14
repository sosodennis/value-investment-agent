# Persistent issuer/date annual discovery checkpoint (#361)

Implementation `e98b80f929bac4e614fce5e1dbcca411daa20fd7`; source-date correction
`1bfa10bc0647efc945c2fdbd3e6c2b4883ac2935`. All prior WIP commits are preserved.
`fundamental-discover-annuals` accepts CIK/date and the declared source revision,
freezes SEC recent/relevant historical submission pages through existing capture
ports/locks and PostgreSQL/content artifacts, and retrieves saved selections.
It retains every original row disposition, source digest and refusal. Parser
limits come from the configured runtime. Latest eligible originals are selected
before checking support; incompatible recent coverage never falls back to older
supported filings. Current ticker metadata is not historical identity evidence.

Architecture decisions precede changes: [initial source operation](https://github.com/sosodennis/value-investment-agent/issues/394#issuecomment-6870624083)
and [source-date root cause](https://github.com/sosodennis/value-investment-agent/issues/394#issuecomment-6871517628).
Real NVE accession `0000724910-08-000006` was accepted at
`2008-05-19T21:33:41Z` and officially filed on `2008-05-20`. The initial selector
incorrectly treated that ordering as invalid. [17 CFR 232.13(a)(2)](https://www.law.cornell.edu/cfr/text/17/232.13)
distinguishes after-hours transmission and next-business-day filing dates. The
correction preserves both fields and independently requires acceptance and the
official filing date to satisfy the decision cutoff. It does not invent a
business calendar or rewrite SEC metadata. The failed first acceptance is kept.

At exact `1bfa10bc`, **2,942 Service/PostgreSQL tests** pass with 17 explicit
external parser-resource skips and one expected duplicate-ZIP warning. Ruff
0.14.10 lint/format, five-owner mypy 1.19.1, both architecture guards, diff and
SEC-enabled service preflight pass. [CI 43555766483](https://github.com/sosodennis/value-investment-agent/actions/runs/43555766483)
passes 12 jobs; the release gate is skipped. CI is not independent review.

The isolated project `value-investment-agent-361-annual-discovery` uses ports
21071/21072 and subnet `10.231.95.0/28`. All 136 installed Python/SQL files match
the exact correction; source digest:
`f52f6ea8c284f98b4636b1a06163257c7fdc6c0a16b515ad068f5567a04c62cc`.
Installed Python/Pydantic/Arelle are 3.12.16/2.14.2/2.47.4.

Two real NVE requests each retain all 839 supplied SEC directory rows:

| Decision timestamp | Result |
| --- | --- |
| 2024-06-01T00:00:00Z | Originals `0001376474-23-000283` and `0001376474-24-000214`, periods ending 2023/2024-03-31 |
| 2026-11-13T00:00:00Z | `FILING_RUNTIME_INCOMPATIBLE`; no selected originals |

Ordinary/concurrent/fresh-process repeats, saved-result retrieval, service/DB
restart and canonical empty-store restore return identical evidence/digests and
`wrote=false`. Repeats prohibit SEC provider I/O. All 45 metadata rows and 11
content objects, including 10 artifact references and previous refusals, retain
their bytes/sizes/mtimes across repeats. The correction adds no new source
capture receipts; both previous receipts and all pre-existing content are
unchanged. Historical-page, failure/interruption recovery and canonical-order
boundaries are also tested with controlled providers; the actual NVE recent
catalog needed no extra historical page.

- Acceptance input: `ca46d348c42b68e5257505fb88c4e1adf5677d0f63a5494d6c77cf33a6465058`
- Acceptance output: `6fca7f1e31d5f0a85ca2043e38012e2b24e582c4b5d41ea2a3b365b9be934de0`
- Canonical backup: `673bd34aa030db091532ee3ec2df74821fdc22d7f102c20d5c2097494d8078fa`
- Checkpoint report: `439314831c605ee5eb1813bc5648217bbd00bd850d89f4ae353f21661dd9031a`

Exact commands, input/output digests, runtime tuple, original bytes, generated
reports and failed checks remain ignored under `.audit/issue-361-annual-discovery/`.
The initial test-database setup error, wrong guard path and real source-date
refusal remain recorded; corrected checks follow them. After successful restore
and verification of a 52-file host backup, only this increment's two containers,
one network and two disposable volumes were removed. All 60 baseline containers
retain IDs/images/start times/status; images/cache and retained source projects
are preserved.

This verifies persistent source discovery, not full automatic preparation or a
real per-share valuation. Next compile the retained discovery into the existing
automatic runner, resolve accounting/award/dated market evidence, and complete
trusted-release/caller-approved numerical acceptance. Independent review, parent
CI and main merge verification remain. No valuation formula, approval authority
or quality promotion changes; #361/#369/#394/#376/#377 remain OPEN, PR #370 draft,
eligible research provisional, incomplete equity cases abstain, threshold null.

## Original-first identity and validation — eaa433ae / c9663d18

Implementation `eaa433ae4052d947a5f0f7c4199c8f098b6ac075` resolves security
identity from original DEI facts and invokes the unchanged strict identity
validator before returning. Single-security originals resolve automatically;
multiple securities and reused tickers require an explicit original security
selector. Retained Tandy/MSFT reports reproduce six automatic and nine explicit
resolutions, invariant to fact order and duplicate observations. The exact
implementation passes 163 identity/mapping/preparation tests and static guards.

Implementation `c9663d183a035bf36bed621baa4517715d780a82` extracts the existing
strict ingestion stage as `validate_filing` / immutable `ValidatedSecFiling`.
Original capture, direct/ZIP integrity, offline SEC EFM/DQC validation and
regulatory refusal retention run before requiring identity or publishing a
snapshot. Existing `prepare_filing` calls this stage, then performs its unchanged
identity/mapping/snapshot work. There is no second parser or financial formula.
The [owning-layer design](https://github.com/sosodennis/value-investment-agent/issues/394#issuecomment-6872077167)
was recorded before implementation.

At exact `c9663d18`, **3,008 Service/PostgreSQL tests pass** (17 explicit external
parser-resource skips; one expected duplicate-ZIP warning). Full Service Ruff
0.14.10 check/format, both changed production modules under mypy 1.19.1, both
architecture guards and `git diff --check` pass. [CI 43559759953](https://github.com/sosodennis/value-investment-agent/actions/runs/43559759953)
passes all 12 applicable jobs; the release gate is skipped.

The SEC-enabled project `value-investment-agent-361-original-validation` uses
21271/21272 and `10.231.97.0/28`. All 136 installed Python/SQL sources match
`c9663d18`; installed source digest is
`2a080d5808ac36f15f95b2ed9c93e0e955ff48892b73dce69e7d2a1644f00aaf`.
Runtime Python/Pydantic/Arelle are 3.12.16/2.14.2/2.47.4. Exact service preflight
passes with SEC identity capability required.

Real retained MSFT originals `0000950170-23-035122` and
`0000950170-24-087843` pass the installed offline parser and integrity boundary
(1,839/1,856 facts). Both preserve the reused-ticker refusal without a selector;
the original common-stock title resolves the intended security. Snapshot
publication is forbidden during this check, and snapshots/facts/mappings remain
empty. Six frozen source reads per execution use existing bytes; external SEC
requests and new downloads are zero.

The second execution reparses the same originals, reuses both evidence artifacts
with `wrote=false`, and preserves all 41 metadata rows and 16 content objects,
including hashes, sizes and mtimes. Its canonical report also repeats unchanged.
This proves this extracted boundary and artifact reuse; persistent bootstrap
cache/plan compilation and complete automatic preparation remain unimplemented.

| Exact evidence | Input digest | Output digest |
| --- | --- | --- |
| eaa433ae retained identity/checks | `1b92b8ea277ba292ece675e56cca406d30dfb50880d5b3d39a52b2a6146a4c97` | `e3e8dba788a666ce9fe2ef309133be8bc41072bdfe491adbcf5c08ca93265ab4` |
| c9663d18 installed original repeat | `c570ab11d1e73c9ebf414c60360f87a600f66cdae244e5288ae5b331761d5125` | `3a17e9bb6177a2639d2c1be163560d57665bdecd952d410b4d7e81475385c2e1` |
| c9663d18 Service/PostgreSQL command | `ffd0fdc9a1b726f2623f81e9f9db74205848c4b820791a2205265da1d3007c09` | `976cb52f2570332eac5353bcafd8a84ada328172581ccf7768a374a53d7d6d6b` |
| c9663d18 static/architecture commands | `0b2f9b1016fecd2ffafd2f06a1b5abfbef391b04141234ce4240c1fb6cd049f8` | `f1b6fee1bd129eae383909c7cec8ff474414cae03c32d55adff9dd9170c99968` |

Installed-repeat report digest:
`b4a74bde1d0181c5f3e4eb280a69b5225e196f50f6eb84f311554a26be997a0a`.
Exact commands, zero exit codes, original/manifest/executor/runtime digests and
complete reports remain outside Git in
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-original-validation-evidence/`.
Ignored `.audit/issue-361-original-validation/` retains the runtime tuple and
failed harness attempts (missing Python import root, missing source form, and
using dict access on a typed evidence record). Corrected harnesses pass without
relaxing production gates.

After verifying a 51-file host copy, canonical backup manifest
`263dcd1ea2522b522d6f645f0f92f57fd98a3a768d65430bb7ccdc35cabde5c2`
and PostgreSQL dump, only this increment's two containers/network/two volumes
were removed. All 60 baseline containers retain image/start/status identity;
images/cache remain. This is backup preservation, not new numerical restore
acceptance. Next wire frozen discovery and retained original identity into the
existing automatic preparation runner, then complete the real caller-approved
numerical flow. The remaining accounting/award/dated-market evidence and parent
review/main gates above still apply; threshold stays null and issues stay open.
