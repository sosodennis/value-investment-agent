# Issue 390 original issuer evidence checkpoint

Status: partial internal-contract evidence; #390, #383 and #376 remain open.
There is no approved financial release, empirical forecast or history threshold.

Implementation commit: `6e8109024f917a76c47b391c1bd0dcfe771f1a68`.
Baseline: `520e17f529ed3525a0702db336ba933bef26307e` on the existing research
integration. Branch: `codex/issue-390-issuer-operating-evidence`. Worktree:
`/Users/denniswong/.codex/worktrees/issue-376-composer-integration-local/value-investment-agent`.
The implementation commit was clean before and after the exact checks; this
later document records acceptance metadata only.

## Evidence

All generated source/report data and command logs remain outside Git under
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/checkpoint-6e810902/`.
This is retained local research evidence, not a shared release service.

| Artifact | SHA-256 |
| --- | --- |
| Exact checkpoint report | `76168667654fa423ae6058d91be390a5dd37ebe3e5065ce63048ac82991598a4` |
| Checkpoint input | `7cdc82e6ab558d4e787d78eac877612c237d5ce5c29c59f75952f78f7b6fe8f4` |
| Checkpoint output | `3a1f9594dff7c0e4074d3f2e411c94b0b42cf43a32b9d35e031a85f22eadbcf9` |
| Original issuer report | `86fea8ce3c66da0b4de287d909881ea2bbf2dd92717a22d1c73d688fbafc6f61` |
| Original issuer report input | `3c7472aedefc296cede6e09af610acc84fde2f6c737bd0f0819edc5ffe111c9c` |
| Original issuer report output | `654fe54cd031a00cbe4f2c785211b93e5cdccaaeab4df25296472dd239c70f6e` |
| Original issuer executor | `8716cc5532d8dd715a61b1f52bae19a2a4b1c1a2ac0835da473079e67970d118` |
| Checkpoint executor | `d1f646950afaf469fe8f79a3d1e32c4bd3fc70d5227588d28beb69701bd885e9` |

The exact executor sources are retained in the evidence root's `references/`.
The checkpoint records Python, Pydantic, Arelle and lxml versions, lock/source
digests, each command argv/exit code and complete content-addressed logs.

## Observed behavior

The three fixed NEWMARKET originals establish issuer-only identity from their
original observations, with 1,687 / 1,485 / 1,378 complete parser facts retained.
The 2016 origin view contains only history and decision originals; the 2017
first-original label remains separate. Future-label and parser/source-hash-swap
refusals retain their complete observations. Missing HTTP receipts, differing
direct/archive bytes and unapproved mappings remain recorded limitations.
Empty/malformed numeric observations survive unchanged and never become zero.

The complete issuer-evidence executor ran twice after initial artifact creation.
Both repetitions returned the same report/input/output digests, zero network
requests, zero new artifacts and `wrote=false`. Every existing artifact's bytes,
size and mtime remained identical. Canonical report writes use the existing
temporary-file, fsync, atomic-rename and unchanged-artifact writer.

## Checks at the implementation commit

All ten recorded commands exited 0:

- Full Fundamental service tests: 747 passed, 48 explicitly skipped for pinned
  external resources or isolated PostgreSQL. The logs retain each skip reason.
- All six historical research/archive test modules: 48 passed, no skips.
- Ruff 0.14.10 check and format check on five changed source modules and the
  new test module; mypy 1.19.1 on the five source modules.
- Agent and Fundamental architecture guards; `git diff --check`.
- Two complete original-issuer evidence executor runs with unchanged artifacts.

The checkpoint also independently loads the owning `071169f953e69713a5a202c9a0030356f1834802`
preparation/calculator modules and verifies exact canonical equality in seven
full-valuation cases. This does not verify later main-chat changes. The three
agent architecture skills were checked and remain current: this increment
changes no agent topology, workflow/state, public service or client contract.

No Docker/service acceptance was run for this pure internal contract increment.
The resource/database skips and synthetic parity cases do not establish that
acceptance, canonical publication or an empirical study result.

## Remaining release and research gates

The internal source view and supplied release reference confer no trust.
Implement and verify issuer-scoped release/serving at the owning boundary,
obtain independent source/semantic review, resolve the four accounting roles,
then execute the fixed original-backed forecast / first-original label / error
/ repeat. Preserve #377 prospective rules, every fixed-100 outcome and the
required main/service acceptance. Formal study forecasts remain 0/100 and
`supported_history_threshold=null`; no issue closes from this checkpoint.
