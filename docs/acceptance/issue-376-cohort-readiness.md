# Fixed100 readiness audit acceptance (#376/#377)

Implementation `38908d49c1c1f17568e65a373842021aadc93a43` on
`codex/issue-376-cohort-readiness`, integration base
`90deee293c8f1f2c33d6a976e1954da03da1b2c4`. Worktree:
`/Users/denniswong/.codex/worktrees/issue-376-cohort-readiness/value-investment-agent`.
Design/ownership: [issue record](https://github.com/sosodennis/value-investment-agent/issues/376#issuecomment-6868660449).
This is a completed offline readiness increment, pending independent review and
serial integration. It does not complete #376 or approve #377. Keep both open.

The command joins the fixed100/589-target manifest, 100 pinned normalized
snapshots and 1,380 consumed canonical archive members without extracting or
restoring the old implementation. It recomputes the explicitly indexed
NEWMARKET conditional evidence with the existing formal Fundamental operations.
No financial formula, source selection, mapping/release authority or quality
status is changed. No generated dataset/report is added to Git.

| Retained evidence | Count/status |
| --- | ---: |
| Selected issuers / filing targets | 100 / 589 |
| Archived issuer/period/field mapping decisions | 19,437 |
| Proposed candidates, requiring review | 5,052 |
| Competing candidates | 1,589 |
| No eligible candidate in archived Companyfacts profile | 12,796 |
| Eligible frozen labels / missing / horizon mismatch | 90 / 9 / 1 |
| Current independent conditional issuers | 1, NEWMARKET CIK0001282637 |
| Exact completed cases / verified issuers | 0 / 0 |
| supported_history_threshold | null |

All three history arms retain 3,125 conditional FCFF comparisons and 125 labels
per registered model. Scenario/model/arm rows do not increase the independent
issuer count. The other99 issuers explicitly lack supplied current evidence in
this index; the audit does not assert that their data is absent everywhere.
Original/amendment identities, availability, period, source hashes, candidate
IDs, mapping versions, failures and missingness remain traceable through the
complete archive references.

The integrity/lexical diagnoses refer to an earlier execution. Their retained
codes count113 unsupported-taxonomy,195 parser-validation,210 archive-size,
37 entrypoint,1 unavailable-validation and1 invalid-payload finding;32 have no
failure code recorded. These are **not current parser pass/fail counts**. The
fixed later original-result reference set is separately checked against
`62f121f386534ea65f0be15b04efc83ed4478d09`. Earlier result digests are not
relabeled as that execution. Source integrity observations75/474/40 retain their
original statuses without granting integrity approval. Candidate gaps never
establish original-disclosure absence or permit zero imputation.

The existing methods/proposal are frozen review candidates, with outcome
inspection disclosed in `docs/research/issue-377-review-freeze.md`. Byte digests:
methods v4 `82c39464824dc3bfd356c03518512eb3f2782e99e3b82a7f525b309e34c3bfa1`;
proposal v3 `9a93879c59c717614f83d497f65c582081c4c690c1ae639a3fc61a1f2fde3ed2`.
No independent statistical/business approval, prospective-power claim, numerical
margin approval or replacement of the legacy100-complete-pair gate is asserted.

## Exact-commit verification

Two fresh processes run the complete command with network connections blocked.
Second publication returns `wrote=false`; input/output/report identities match,
with zero new artifacts and unchanged existing bytes, sizes and mtimes. Pinned
snapshots, manifest and all supplied conditional artifacts are also unchanged.
The existing publisher uses locking, temporary file, fsync and atomic rename.

At this exact commit, **136 focused tests pass**, including30 new readiness
boundary tests. They cover archive corruption/canonicalization/unsafe or
ambiguous members, all100/589 retention, duplicate/omitted/substituted mapping
and source records, issuer/period/availability/amendment/role conflicts, future
inputs, failed-source retention, independent denominators and immutable reuse.
Ruff0.14.10 check/format, source-aware mypy1.19.1, both architecture guards and
`git diff --check` pass. Wrong exact SHA and duplicate JSON controls exit2
before publication. Every command, exit code and input/output digest is retained
in the external proof's eleven command receipts.

Initial implementation `0d19aea7` failed real CLI decoding before publication:
strict Pydantic rejects Python lists for tuple fields at `model_validate`.
Correction `38908d49` uses the JSON boundary after duplicate/canonical checks;
the new regression exercises actual JSON arrays. The initial failure receipt is
retained under the earlier checkpoint; history is preserved.

Canonical runtime: CPython3.11.15, arm64/Darwin, Pydantic2.14.2,
Arelle2.47.4, cryptography50.0.2; lock digest
`229bc76c75019d54df8c1cba240839bacf01e56d7493f4bc615e058c4e5f6f11`.
The interpreter comes from the retained Transition environment; `PYTHONPATH`
explicitly selects this checkout's Service and scripts. No installation is
changed. Docker, DB, .env, trust and browser state are untouched. New Docker/live
SEC/service acceptance is not claimed for this offline CLI; underlying #438
service evidence remains a separate result.

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/cohort-readiness/38908d49c1c1f17568e65a373842021aadc93a43/`.

| Artifact | SHA-256 |
| --- | --- |
| Fixed manifest | `448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a` |
| Readiness input | `adf126354ab50fd826b539132a8ca80667ac5b0e029f8db9d5a2c6f999ccf40b` |
| Readiness output | `0c1d604a6ba4c26126bc0da5ad1c186e8da27ba9bd202252706cec3ccd276309` |
| Readiness report | `0df0a4122468c92d69c7db592fe6d14ae3995fed52dbbc487e073f4f17684e4a` |
| Verification input | `0c5696d7251d57ea020cf4e3885df98ff7f4d433408ae974dd876a50fc4f4344` |
| Verification output | `9f8ec30cb0eef1144e4f7d1f2f96bf516f09fe2a995de0a8bbe82ea8f161b858` |
| Full repeat/check proof | `cc695d458cca07024fde58e5292b1e197ecd4ea47fcfcc83957d67a574fdb101` |

Reproduce with the retained driver, whose digest is in the verification inputs:

```sh
PYTHONDONTWRITEBYTECODE=1 \
  /Users/denniswong/.codex/worktrees/issue-376-transition-evidence/value-investment-agent/fundamental-service/.venv/bin/python -B \
  /Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/cohort-readiness/verify.py \
  38908d49c1c1f17568e65a373842021aadc93a43
```

The driver requires this exact clean commit. Later acceptance-only metadata can
be reviewed on the branch; replay the implementation in an independent checkout
when reproducing its exact SHA. Required next evidence: independent code/methods
review, original-period semantic adjudication and actual authenticated releases,
then full fixed-cohort model losses and uncertainty under approved criteria.
An underpowered/null empirical conclusion is valid only after that study, not
because this audit finds unfinished engineering/evidence work.
