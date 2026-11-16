# Fixed-cohort label audit acceptance (#376/#377)

Implementation: `84ffa4e6c41fdc134ad00da7f7ec6b8d0d20d887`, based on integration
`938528909914bbb1b102c1583017401dfee80b46` (includes PR #435). This independent
increment adds one offline CLI, its boundary tests and
[scope/run instructions](../research/issue-376-label-inventory-audit.md).
It does not change parent source acquisition/mapping, financial policy, composer,
release authority or any existing study output. Generated evidence stays outside
Git; the previously retained 100 snapshot files are inputs, not newly committed
historical data.

## Observed fixed inventory

All 100 compressed normalized snapshots match the manifest's original hashes.
Their 1,931 annual filing rows reproduce every frozen first-original selection
using the existing Fundamental selector:

| Disposition | Issuers |
| --- | ---: |
| Selected label with frozen eligible horizon | 90 |
| No later annual period in retained snapshot | 9 |
| Selected first original with 731-day gap | 1 |

The nine absent labels retain null horizon eligibility rather than being called
nine measured horizon mismatches. The 731-day case is CIK `0001137091`, decision
`0001193125-16-482422`, label `0001137091-19-000016`. The full report retains all
issuer rows, annual filings, amendments, later candidates and selected labels,
plus snapshot hashes and captured submissions URI/response-digest metadata.

These counts describe the frozen normalized inventory. No raw-response
normalization/completeness or reason for missingness is established. There are
no new forecasts, accounting reviews or authenticated releases; this does not
increase exact study cases or independently sampled conditional issuers. The
maximum of 90 is before all financial/release/model gates. Threshold remains
null; #376 and #377 remain open.

## Exact-commit verification

At the implementation SHA, 124 tests pass across label audit, methods, precision,
evidence export, windows, history report and cohort tests. Ruff 0.14.10, changed
file format, source-aware mypy 1.19.1, root architecture guard, Fundamental guard
and `git diff --check` pass. Tests cover amendment-only earliest periods without
later-original substitution, retained amendments, equal-availability ambiguity,
duplicate/conflicting filings, issuer/date/accession substitution, missing or
corrupt snapshots, unique JSON fields, deterministic ordering, fixed denominator
and immutable publication. An initial older general Ruff pre-commit hook
rejected a boolean type comparison; it was corrected before the implementation
commit. Both the general and pinned hooks then passed.

Two fresh Python processes run the actual CLI against all 100 external copies
of the hash-verified snapshots. Socket connection calls are disabled in each
audit process. Both produce identical report/input/output digests. The second
returns `wrote=false`, adds zero files and preserves every existing byte, size
and mtime. All 101 input files also remain unchanged. Wrong exact SHA and a
deliberately corrupt gzip each exit 2 before creating an output directory.

Runtime: CPython 3.11.15, Darwin arm64; the report also pins source/tool and
Fundamental lock digests. No SEC acquisition, database, Docker or service-backed
acceptance is claimed for this offline-only diff. Parent uncommitted files,
trust configuration, snapshots, containers and volumes were not modified.

| Artifact | SHA-256 |
| --- | --- |
| Frozen manifest | `448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a` |
| Audit report | `1281d88af5e4bb38327d6fd330e0f5c906ef7ffe51d57109df2855d022d650b6` |
| Audit inputs | `819afeb77fe9a005c13ce48ff5f4ee50d5954a4bae9460441fef6db3d24394a7` |
| Audit output | `b5f26f537e3dc1e23153bb02161ad2d20d5a5475a62e685a31b86be3b541f082` |
| Verification proof | `8879dc288e6a5d136f8e728262302b514535d79e0ad25f0359f95786826f03c1` |
| Verification inputs | `b06cd3c52c9221f4e2fac1858b78dfc04cba2454f1998890e33a882ef736d2a3` |
| Verification output | `bc05ff6b8f8d81d41b486d700d826abd04c96be499072ca0173a300ea97dcc64` |

External root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/label-evidence-audit/84ffa4e6c41fdc134ad00da7f7ec6b8d0d20d887/`.
The `commands/` directory contains canonical command receipts with exact commit,
argv, exit code, stdout/stderr and input/output digests. `verification/` contains
the proof, `audit/` the immutable report, and `inputs/` the unchanged inputs.
Reproduce using the committed CLI instructions, or the external verifier:

```sh
python -B /Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/label-evidence-audit/verify.py \
  84ffa4e6c41fdc134ad00da7f7ec6b8d0d20d887
```

Use the exact clean implementation checkout and its pinned runtime. Verification
receipts preserve observed command outputs; their identities can differ when a
fresh first publication becomes an existing-artifact reuse. The audit's semantic
output digest remains identical. Pending delivery gates: final-head CI,
independent engineering review, serial integration and merge verification.
