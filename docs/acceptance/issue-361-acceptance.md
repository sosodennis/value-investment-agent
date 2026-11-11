# #361 persistent source preparation and valuation flow

The accepted outcome is the complete normal Fundamental Service flow: issuer and
valuation timestamp, eligible SEC evidence, persistent canonical facts/snapshot,
automatic preparation, the existing #352 composer/calculator, and retrieval of
the persisted valuation artifact. Repeated requests reuse eligible evidence.

The repository owner revised [#361](https://github.com/sosodennis/value-investment-agent/issues/361)
on 2026-11-11. The fixed-100-issuer history-threshold investigation is separate
research. Its historical failures remain evidence, but its corpus is not a
runtime dependency or this issue's delivery criterion. Neither model has an
approved numerical history threshold; `supported_history_threshold` stays null.
The existing provisional/abstain, source availability and release-trust rules
still apply. #351–#355 acceptance is unchanged and #350 is not started.

## Flow and acceptance

1. Resolve source identity using CIK, original accession, valuation timestamp and
   source-selection profile. Read existing receipts/snapshots first; fetch missing
   eligible evidence without exposing future facts or overwriting older bytes.
2. Persist immutable source bytes in the service-owned content volume and
   manifests/facts in PostgreSQL. Capture failures retain raw evidence and reasons
   without publishing an approved snapshot.
3. Prepare with the formal #352 composer and trusted mapping/model/policy
   releases. Existing caller approval/override contracts remain. A project signer
   does not replace semantic review or supply missing facts.
4. Validate/calculate with the existing deterministic calculator and retain the
   result plus source, mapping, model and policy digests. Calculation stays
   stateless; do not introduce server-owned valuation sessions or jobs.
5. Demonstrate one supported real-filing-backed numerical result, artifact
   retrieval, repeated acquisition/valuation without duplicate evidence or
   artifacts, concurrent deduplication, restart against the same store, and
   digest-checked recovery to an empty isolated store. Document unsupported
   historical profiles and missing/conflicting inputs as explicit refusals.
6. Run exact-commit tests, architecture/lint/type/contract checks, isolated #361
   Docker acceptance, complete-flow repeat and review/CI before merge. Verify the
   merge commit before closing the issue or cleaning issue-owned resources.

The required manifest profile is `persistent-valuation-flow-v1`.
[Runtime metadata](issue-361-runtime.json) is WIP; every new flow check is
`not_run`, and the prior runtime tuple must be revalidated. Passing research
checks cannot verify this scope. #369/#371 still limit requests that require
unsupported historical evidence; #372 remains a separate legacy release gap.

## Scope checkpoint

[Checkpoint evidence](issue-361-scope-checkpoint.json) records exact commit
`608a8eeb5e419968805db8beb166c84997e50574`, commands, exit codes, input/output
digests, runtime pins and [CI](https://github.com/sosodennis/value-investment-agent/actions/runs/42964782635).
CI passed 12 executed checks; its Fundamental suite passed 455 tests with 11
environment-dependent skips. The legacy release job was skipped. The isolated
`value-investment-agent-361-flow-tests` PostgreSQL regression passed all 17 tests.
Its tmpfs-only database container and network were removed after verification;
all 37 pre-existing container identities, image IDs and start times were unchanged.

This checkpoint verifies scope separation and the remaining regression suite.
It does not verify the complete valuation flow. At this commit,
`FundamentalApplication.resolve_snapshot()` reads released snapshots and returns
`SNAPSHOT_NOT_FOUND` on a miss; it does not initiate acquisition.
`prepare_valuation()` requires a pinned release containing the selected snapshot
and facts. Connecting a newly acquired snapshot to trusted preparation, proving a
real-source numerical result and verifying service restart/restore/repeat remain
implementation and acceptance work. Existing release signatures must not be
bypassed to connect those steps.

## Engineering Checkpoint: Retained SEC Originals

Implementation commit `7e9a1f17723f0c8f3bf35fbe214c5ec7b6157ca6` adds
cross-date reuse for exact accession-scoped SEC archive bytes. Each valuation
timestamp and source profile still receives its own decision receipt; mutable
submissions remain date-scoped. Latest-filing acquisition now retains the
selected original package after accession selection. Interrupted publication
recovers from the immutable archive receipt, and corrupt evidence fails closed.

The checkpoint input digest is
`6da1b6b8eaccd1ff2530bc4eb42e8423a8c66537892f4499adccc3c8da982906`; its
output digest is
`1ff1cc796ca37cd0deef315db154509230237e389f7f5e0aae4a75c9831072ca`. The
tested runtime was Python 3.11.15, Arelle 2.47.4 and Pydantic 2.14.2 with
`fundamental-service/uv.lock` SHA-256
`57b9ea3f92002720d4bce735df3316df071479da4c0599a31ae914e9e6c32a18`.

- `uv run --frozen --extra dev --project fundamental-service pytest -q fundamental-service/tests/test_sec_capture.py fundamental-service/tests/test_source_acquisition.py`: exit 0, 62 passed; output SHA-256 `de4248f2bff0b3dc39c1d9348cf7218dcc0c16425e82b7e73a03dd2f8990f91e`.
- `uv run --frozen --extra dev --project fundamental-service pytest -q fundamental-service/tests`: exit 0, 449 passed and 28 skipped; output SHA-256 `667a1b9186a8fe4f6f3043ade1e130bdb0827d8850080958b787a59b44c882ef`.
- `uvx --from ruff==0.14.10 ruff check fundamental-service` and changed-file `ruff format --check`: exit 0; combined output SHA-256 `c6486b51f483249343d4a4bdb91c41be31f0bdc28887b2f4cd4800e174f8bd6b`.
- `MYPYPATH=finance-agent-core uv run --frozen --project fundamental-service --with mypy==1.19.1 mypy --no-incremental --follow-imports=silent --ignore-missing-imports fundamental-service/src/fundamental_service/sec_capture.py fundamental-service/src/fundamental_service/source_acquisition.py`: exit 0, no issues; output SHA-256 `f9b031e5c45aa702cd4fef028d465551cb20a2c4698e0913c7b00766b20ac4d8`.
- `python3 scripts/architecture_guard.py`: exit 0; output SHA-256 `6c8e024ff94859e9781de1f4a3201c70e338bc90774702d8ac83afc8a9a15ab9`.
- `git diff --check origin/main`: exit 0; output SHA-256 `1393aefd211f885a41b5b3a966b54c00f8d80989148cc9d6c51a2ebe869f5255`.

This checkpoint covers source retention and acquisition retry behavior only. It
does not satisfy any full-flow gate by itself; all 19
`persistent-valuation-flow-v1` acceptance checks remain `not_run` until their
complete behavior is exercised against the isolated service runtime.

## Engineering checkpoint: source preparation and history canary

Implementation `0fb1abe76fb10de5ee9ce40f30f4a94d68c15885` adds the one-shot
`fundamental-prepare-source` command. It coordinates the existing acquisition,
trusted candidate canary/publication/activation, #352 composer and caller-approved
calculation. An acquired but unreleased snapshot yields `release_required`;
prepared evidence yields `approval_required`. Permanent source refusals are
retained as `blocked`; transient errors and authorization denials still propagate.
Stored snapshots can resume through a trusted candidate without provider I/O.
There is no server-owned valuation session, fabricated approval or new formula.

The #375 release canary now validates all declared annual fact IDs and digests,
source membership, availability and released mapping bindings. It retains the
latest-fact canary and rejects invalid older periods, unknown amendments and
conflicts. Both artifact stores expose publication receipts and reuse identical
metadata/bytes with `wrote=false`; corrupt bytes are not replaced.

[Exact checkpoint evidence](issue-361-preparation-checkpoint.json) records commands,
exit codes, runtime pins and command-output hashes. Input digest:
`426f8b1ff61511635d38caa7e156ec4eb6b7957ab8ebff6e6b83cb9cd530fb05`;
check-output digest:
`fb3aed3069a41e6a18789f8987312b24452c56b437d1004406f74db582131074`.
Fundamental tests against the isolated PostgreSQL project passed 493 tests with
11 optional parser/runtime skips. Acceptance-manifest/preflight tests passed 17;
Ruff, changed formatting, four-source mypy, architecture guard and diff checks
passed. PostgreSQL tests verify concurrent publication receipts, content mtime
preservation, corruption refusal and preparation/calculation reuse after metadata
restart, using synthetic fixtures.

These checks do not establish real-filing numerical success or a complete service
restart/backup/restore acceptance. Multi-filing composition and reviewed financial
role coverage, real-source numerical success, service-backed repeat/recovery,
independent review, CI and main merge verification remain required. #361 and #375
remain open; all 19 full-flow gates remain unverified. The next implementation
unit is real-source coverage and recovery, not threshold promotion.

## Engineering checkpoint: multi-original history

Implementation `1a1e441d00c05f154d061a71064892a119ec7168`, with API test
adapter corrections in `e44aa780d8e439e26102c5ce1ef5b94a552cb211`, adds a
deterministic history snapshot referencing each retained original and its own
parser-bound integrity. This preserves original source ownership while exposing
their fact history to the formal #352 composer. Combining raw facts under one
original's integrity would not establish that relationship. No facts or valuation
formulas are changed.

The unreleased preparation plan is now V2: one to six ingestion requests, sorted
distinct original accessions for multiple inputs, matching issuer/date/runtime
pins, and a complete model-role union. Individual filings may map only the roles
they support. Existing V1 outcome receipts keep their original shape. Canary,
serving, cached resolution and offline recovery re-read every component. Missing
or changed retained originals refuse the history without treating corruption as
a new acquisition request. Repeating composition preserves bytes and mtime;
concurrent composition produces one history identity.

[Exact checkpoint evidence](issue-361-history-checkpoint.json) records the final
implementation commit, commands, runtime pins, failure retention and synthetic
input/output identities. Input digest:
`43fa88e1a67536ebe2cdb6fedb7e3dd68af46d8ac8b7d7acc60209efe9311091`;
command-output digest:
`d3c8680957fcaa08f0df064b3368ce44fde597249c5cd5193bac0bec2b20f04d`.
The exact suite passed **530 tests with 11 optional runtime skips**, plus 17
acceptance-tool tests. Ruff, changed formatting, six-source mypy, architecture
and diff checks passed. The first exact run's 20 API adapter failures remain
recorded; fixtures now provide the integrity field and read the requested
snapshot ID without relaxing production checks.

Synthetic originals demonstrate provisional numerical preparation/calculation,
unchanged repeated output, source corruption refusal and recovery of the same
composition into a separate empty PostgreSQL store. The complete synthetic
history backup digest is
`6727953622aca133c698c3661c9161f91f5849af153c34a0dfddde0bb5fb3f48`.
Only this run's tmpfs database/network were removed; all 62 pre-existing
container identities, image IDs and start times match the baseline.

This is engineering evidence. Reviewed real issuer/period role coverage,
real-filing numerical success, complete service repeat/restart/restore,
independent review/CI and main verification remain required. #361 and #379 remain
open; PR #370 remains draft. The 19 full-flow gates and history thresholds are
not promoted by synthetic success.

## Research preservation and removal

Baseline `59830e161c9300e44b2b7b54eea3e43567835bff` has tree
`c155f53fcc8f099c2bef6469bbc9ace9f9e60ee0`, identical to pre-squash
`a74238ec4433aaadf85e285f6fa399bdb366292e`. Its original checkpoint chain remains
at local branch `codex/issue-361-replay-evidence-presquash-a74238ec` and in the
verified `source-history.bundle` alongside the research archive.

[Archive reference](issue-361-research-archive.json) records the exact baseline,
input digest, archive/manifest hashes and local preservation directory. The
archive contains all 10,358 baseline #361 acceptance/research files. All members
were compared with the committed bytes, then restored to a clean temporary
directory and checked against the per-file SHA-256 manifest before removal.
The branch removes 10,357 files and replaces the old runtime acceptance with the
new WIP scope. No source bytes, prior failures or checkpoint history are lost.

The archive is a local research backup, not a published service snapshot or a
shared production recovery source. This preservation does not satisfy the
complete flow's persistence/restore acceptance. Production storage and its
export/import or pinned source preparation must be verified separately.

To inspect or restore research, obtain the referenced archive and `manifest.json`
from the recorded preservation directory, verify both hashes against the checked
reference, and extract to a separate directory. Do not restore research over the
current worktree or import failed/unapproved observations as canonical facts.

Research-only replay, proposal, signing and fixed-inventory validation commands
and their tests are also removed from this product PR. Their exact paths and
hashes are recorded in the archive reference and are recoverable from the Git
bundle at the baseline commit. The production acquisition, retained-capture,
parser, mapping, preparation and calculator tests remain in scope. A clean CI
checkout must not require the local research archive to run those tests.

```sh
git bundle verify /path/to/research-archive/source-history.bundle
shasum -a 256 /path/to/research-archive/research-evidence.tar.gz
shasum -a 256 /path/to/research-archive/manifest.json
mkdir /tmp/issue361-research-inspection
tar -xzf /path/to/research-archive/research-evidence.tar.gz \
  -C /tmp/issue361-research-inspection
```

The archived original manifest lists every path, byte length and content hash.
The prior preflight at digest
`e298ab873bb96a44a8d8e916a8aeb1f7d110dd335b2f2fac79e2a84bf5085de0`
remains in that archive and at the baseline Git commit. Its zero canonical
forecasts are not changed or claimed as success.

## Engineering checkpoint: persistent backup and recovery

Implementation `1997fdb77206ee0fae465985c14f1e6d37f96cf8` adds the offline
`fundamental-persistence export/restore` operator command. It exports sorted
canonical metadata rows and hash-checked source/content bytes as an atomic
versioned bundle. Restore accepts only an empty or identical metadata store and
a matching content subset, imports metadata transactionally, verifies the result,
and preserves incomplete staging for retry. Repeated export and restore return
`wrote=false` without changing existing content. The operations runbook records
the writer shutdown, compatible runtime and separately pinned trust/configuration
requirements. This is service-owned persistence work; valuation formulas, release
trust and caller approval are unchanged.

[Exact recovery checkpoint](issue-361-recovery-checkpoint.json) records commands,
exit codes and runtime pins. Input digest:
`de73787c814237d053a77326ad4371263e2fac7d429451f6a62173758294890d`;
command-output digest:
`231b19d9284abcb86ffbc79e477cd3a92a7b917cee3bf2ad2ee6d98803ac405e`.
The exact implementation passed 505 Fundamental tests with 11 optional runtime
skips and one existing serializer warning, 17 acceptance-tool tests, Ruff, changed
formatting, one-source mypy, architecture guard and diff checks.

The synthetic formal-composer calculation was restored into a separate empty
PostgreSQL database and recomputed with the same valuation input/artifact digest;
its repeat returned `wrote=false`. Its backup digest is
`a5a146b1d4071edc6fff0b7bd547f2e968ddc07de30cd20859dbec24f7476744`;
its valuation artifact digest is
`23c430a5cd5c4ef930001a9064ca0e123670a4903eea249508ab60a93b750332`.
Negative cases retain evidence and reject corrupted, incomplete or conflicting
stores; interrupted import rolls back and retries. Four complete synthetic backup
bundles remain verified outside Git; damaged negative fixtures are not counted
as usable backups. Only this run's disposable tmpfs database/network were removed;
all 62 pre-existing container IDs, image IDs and start times were unchanged.

Real original-filing role coverage/multi-filing composition, actual numerical
success, the complete isolated service repeat/restart/restore acceptance,
independent review, CI and main merge verification remain outstanding. This
checkpoint does not verify any full-flow gate by itself; #361 stays open and
PR #370 stays draft. Neither model has an approved history threshold.

## Source-plan mapping checkpoint

Implementation `16ce3baa841d68de8e2fb307a3fb4697e6318df1` binds release reuse to the plan's mapping decision IDs, versions, roles and original accessions. It also verifies all declared historical fact digests before reuse. A candidate containing a different reviewed mapping cannot substitute that mapping for the actual facts. Conflicting references to one mapping ID are rejected at the plan boundary.

Exact-commit isolated PostgreSQL engineering checks: **538 passed, 11 optional runtime skips**; **17 acceptance-tool tests passed**. Ruff, changed-file formatting, six-source mypy, architecture guard and `git diff --check origin/main` exited 0. Input digest `cf536b86c41055cb5d711ec484cedbb389286b6f3f05e6b1f37fba5b47dc4f5d`; command-output digest `8281fec427035e0def7c17c3a2a5174576c926b617dc5b393b46f0b68c84f4d0`. Exact commands/runtime and retained failure-log digests are in `issue-361-source-plan-checkpoint.json`. Disposable project `value-investment-agent-361-flow-tests` was removed; the 62 pre-existing containers retained their IDs, images, start times and status.

Prior-head CI `42986810091` at `7f589080` passed all 12 executed checks; `fundamental-release-gate` was skipped. This does not establish CI for `16ce3baa`, independent review, real-source numerical success, or the 19 full-flow gates. Threshold stays null. Next: concrete real original-filing financial-role coverage and semantic review, then numerical service repeat/restart/restore.


## Accounting-role evidence checkpoint

Implementation `8397497b984cfbceb5df249e445461fd2ab51779`, with the test-boundary fix
`883e8e13736425967f8e80d842331154cc44b2b2`, adds exact source-bound accounting
components, cited absence and explicit unresolved roles. Direct observed
facts/mappings retain their canonical bytes. Canary, HTTP evidence serving and
backup/restore recheck the rule, released mapping and validated original.
Classification uses a fixed Decimal context; no #352 valuation formula changes.

At exact `883e8e13`: **569 Fundamental tests passed, 11 optional runtime skips**;
**10 Agent client tests** and **17 acceptance-tool tests** passed. Ruff, changed
format, eight-source mypy, architecture and diff checks passed. Input digest
`143d17173a31bfb93ab16009219df304bb96badd288ab0611dba1d69bc46c63b`; output
`b5978bf81959136a72510b6edd5577e74e3ca2964b0386c2e51f012e8ad5ffbd`.
[Exact commands, runtime and failure retention](issue-361-accounting-checkpoint.json).
The first exact run's forbidden test import and working adapter failures are
retained. Disposable PostgreSQL project `value-investment-agent-361-flow-tests`
was removed; all 62 baseline containers retained their identity, image, start
time and status.

These are engineering checks, including synthetic source/reviewer fixtures.
They grant no actual issuer mapping approval, release or numerical acceptance.
Real issuer/period coverage and review, all 19 full service gates, independent
PR review, latest CI and merge/main verification remain incomplete. #381, #361
and PR #370 remain open; the PR stays draft and history thresholds stay null.


Real-source increment at `a729700f68629d4fc5978ac58f5f2f62fa8bb7b4`: AAPL original
`0000320193-24-000123` passed strict EFM/DQC using the retained complete taxonomy
cache: 1,127 facts, no blocking finding, no parser network attempts. A second
independent parser execution produced identical replay digest
`05f406e6ce8352c0e25c6a3371b52bbf7ae49c90c76b01602da2b638846a010d`.
Original-validation input `6a79284558ab75ca1145f39400675d93cc43140a3cf5a00e67a3582dd10043d0`,
output `3a2722aa27cb2f1665f0be1f3a0d6f14bc99d6ed3848b698f13352b0d12dee57`.
The old fixture lacked normalization headers; the missing raw response metadata
was actually acquired and retained by the existing source adapter. A remembered
taxonomy directory was empty; its failed validation is retained. No source header
was invented and no DQC rule was waived.

The accounting proposal now retains **62 provisional period facts across 25/32
roles**, including 3 derived classifications. Input
`6c9700cee047716b6848044b120f3a6c4ab89121df6f58f11feed4bb06fe9ee0`, output
`11f2dd2a7f08b8cf23a4e70485c8d90481ab61f7e7aec1ea6327cd9f979a5047`.
Both original-validation and proposal cache repeats returned `wrote=false` with
identical content/mtime inventories; source repeat made zero provider calls.
Raw bytes, complete reports, scripts and proposed mappings stay in ignored
service evidence storage, outside the PR. The compact checkpoint records their
commands, exact commit, pins and digests.

Finance-lease cost, contract assets, preferred claims, noncontrolling interests,
convertibles, point-in-time dilution and other share classes remain unknown.
Related RSU evidence is retained with its AwardTypeAxis; it is not silently
reclassified as consolidated dilution. No absence is approved, all mapping
proposals remain unreviewed, forecast/valuation count is zero and threshold null.
Additional original history, actual review and full numerical service acceptance
remain required. CI at `a729700f` passed all 12 executed jobs; legacy release gate
was skipped. All three architecture skill entrypoints remain current.
