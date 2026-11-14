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
