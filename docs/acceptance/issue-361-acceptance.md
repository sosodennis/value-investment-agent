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
## Original preparation checkpoint cd514ae8

At exact implementation `cd514ae8b12f67c3c00e5459363097ae39eaacb5`, the
Fundamental suite passed 578 tests with 11 optional runtime skips; 10 Agent
client tests, 17 acceptance-tool tests, Ruff/format, nine-source mypy,
architecture and diff checks passed. Isolated PostgreSQL regression input:
`c59705fa699083fba4518f86667e3f88d2b5b38245032472588a0acead866206`;
output: `e7575588d9319dfceb1ba411c22b88259b5859c355f6eb4b3efe81dc8cbc9a63`.
The disposable tmpfs project was removed; all 62 existing containers retained
their IDs, images, start times and status.

Real AAPL FY2023 original `0000320193-23-000106` now passes the existing
`SecIngestionService.prepare_filing` source and original-DEI identity gates:
1,164 parsed facts, strict EFM/DQC, no blocking findings or parser network
attempts. #382 fixes omitted archive graphics in prepare. #384 binds the
requested ticker and title to one original security class context while
retaining other listed securities as evidence. The original failures remain
retained; no findings, identity checks or mapping approvals were waived.

Real prepare input:
`cd6b9c44106a44475f7ba114d30a3e7d71c002e25ab382bec1173e24f71476d1`;
output: `5d4da70fe5b7b8ee0eb05972329575da9665165b8add622754e2978ce5ebd5e6`.
An independent service execution reran the parser and reproduced snapshot,
fact, integrity, identity evidence and semantic/replay digests. It returned
`wrote=false`, `input_wrote=false`, made zero provider requests and left all
46 retained source/preparation files' content and mtimes unchanged.

This is provisional source preparation, not approved financial-role coverage,
snapshot publication, a trusted release or numerical valuation. All full-flow
gates and blockers #375/#379/#381/#382/#384 remain open pending actual
acceptance, review, merge and main verification. The compact evidence lives in
`issue-361-accounting-checkpoint.json`; full SEC artifacts stay outside Git.

## Disclosed amount checkpoint c1e409c7

Exact implementation `c1e409c7e5ec6d7fbe125fc74ec94436eeaeaa43` retains a
disclosed amount's original text, exact offsets, unit, scale and reported
precision. Wrong periods, partial numeric tokens and incomplete role scope are
rejected. The 124 retained facts and 50 retained mappings keep their digests.

The isolated PostgreSQL regression passed **609 service tests**, with 11 optional
runtime skips, including disclosed-evidence store restart and backup/restore.
The 10 Agent client tests and 17 acceptance-tool tests passed, together with
Ruff, changed formatting, nine-source mypy, architecture and diff checks.
Input: `8ba2b74c0347e4c2100e5750ed5b0cb15c02719acfe57805841df8ca6243043e`;
output: `411d15beab6bfd4bc81e707c0062d1de31968cf717876b91580eb66b26d052b9`.
All 12 executed CI jobs passed; the legacy release job was skipped. The owned
tmpfs PostgreSQL project was removed; all 62 baseline containers are unchanged.

A retained AAPL FY2024 original also demonstrates a provisional transcription of
the narrower **fixed-payment operating lease cost**, with value 2,000,000,000 USD
and reported decimals -8. It matches the same-period numeric original observation.
Input: `ab445da6ec9074fb609fc011977592232becc43f9e086f9a108be47c0789f356`;
output: `4246bb1f15a3214abb48e0e01d9a220d4784e3b20138cbb4774f701c566608bc`.
The repeat returned `wrote=false` and `input_wrote=false`, with identical digests
and zero source downloads. The earlier diagnostic string-comparison failure is
retained; comparing Decimal values fixed the probe without changing source data.

This transcription does not establish complete lease costs, independent mapping
approval or numerical valuation. Complete accounting and dated market-policy
evidence, actual review, caller approval and all 19 service gates remain required.
The next step is the supported real-source review packet. PR #370 stays draft,
#361/#381 stay open, and `supported_history_threshold` remains null.

The follow-up source-bound review packet at exact evidence commit
`1c9e14b7562a735fd255dc6fcbaeaec2b54ca9b9` retains related parsed observations
from both validated originals for finance lease cost, contract assets, preferred
claims, noncontrolling interests, convertibles, point-in-time dilution and other
share classes. All seven remain `unknown`; related observations and missing
tags establish neither complete numeric coverage nor economic absence.
Input: `6703c7fbb6f6fa745123b885ed278d6e25e3d223e938e3599518252467054e0e`;
output: `da7f96fd20be8d638f6c66299fee4a912de6a9a55ec8c92fda0cda5b69d448f7`.
The repeat returned `wrote=false` and `input_wrote=false`, with no downloads.
Full observations remain outside Git; their source, parser, script, runtime and
artifact digests are in the compact accounting checkpoint. This tests the
remaining evidence gap directly: transcription support cannot supply an
undisclosed or unreviewed financial role. Current CI at `1c9e14b7` passed.

## Formal composer lease correction (#385)

Implementation `ac47fc2c434521dcd8df7ebf57f5233ac5b140bb` corrects the existing
composer's equity-bridge classification to the declared `lease-treatment-v1`.
The old composer deducted operating lease balances even though operating lease
costs remain in FCFF. For both models, increasing only those balances by 1,000
incorrectly reduced equity by 1,000. The regression now leaves equity unchanged;
increasing finance lease obligations by 100 still reduces equity by 100. All
six missing lease-role cases still abstain, and operating lease observations
remain in the input. Deduction provenance names only finance obligations.

The corrected input identifies `fcff-forecast-composer-v2` in optional preparation
provenance, bound to the input digest and caller approval. Direct caller inputs
omit this provenance when unset. Existing artifacts retain their identities.
Exact PostgreSQL regression: **619 service tests passed / 11 optional skips**,
10 Agent client tests and 17 acceptance-tool tests passed. Ruff/format,
ten-source mypy, architecture, contract generation and diff checks passed;
contract generation left tracked files unchanged. CI passed all 12 executed
jobs; the legacy release gate was skipped. Input:
`dd6bdb17883aa2fa503673e5b2992eb3030e83386e46a3d03d774fd79583c3c5`;
output: `f10dda7157193dba3a2cb055a893ece561d65a4e8abdb751cb3229b507b88cd6`.
The owned tmpfs PostgreSQL project was removed; 62 baseline containers are
unchanged. Before/after failures, commands, runtime and digests are retained in
the compact accounting checkpoint.

A separate same-input probe at this commit exposed [#386](https://github.com/sosodennis/value-investment-agent/issues/386):
caller Decimal precision/rounding changes the calculator's output digest. One
input produced three result digests. This remains a determinism blocker despite
the passing existing regression suite. Fix numeric-context ownership and resolve
the canonical/deployed precision-policy drift before claiming full replay
acceptance. Real-source role/policy review and all 19 service gates remain
incomplete at that checkpoint; #361 and the blockers stay open, PR #370 stays
draft and thresholds remain null.

## Fixed numeric context (#386)

Implementation `07627d14984d758a5054057feba8ebafafd42cb2` removes the import-time
Decimal mutation and runs existing Fundamental numeric boundaries in a fresh
fixed context. This retains the model inventory's declared
`decimal-50-end-of-year-v1` (50 digits, HALF_EVEN), including explicit exponent
limits, traps and local restoration on both success and refusal. The target
arithmetic table now records this V1 policy; a 34-digit policy would require a
separate version and replay evidence. No existing artifact is rewritten.
Prepared inputs identify `fcff-forecast-composer-v3`, so their caller approvals
are bound to the corrected preparation version. Financial equations remain in
the original composer/calculator. The challenger retains its independent
equations and uses the declared numeric context for its comparisons.

Against explicitly imported archived `1a4ca00f` source, 25 behavior tests fail;
the new implementation passes all 26 numeric-context tests. The exact full
regression passes **645 service tests / 11 optional runtime skips**, 10 Agent
client tests and 17 acceptance-tool tests. Ruff/format, sixteen-source mypy,
architecture, diff and contract generation pass; generation leaves the tracked
tree unchanged. PostgreSQL tests execute low-precision/trapping restart and
fresh-worker restore, preserving artifact bytes and no-write receipts.

The deterministic engineering replay covers both models' prepared inputs and
Monte Carlo reports in four caller contexts and two fresh worker threads. All
six runs have one output digest. A second complete execution reuses the input,
output and report (`wrote=false` for all three); artifact paths, sizes and
modification times are unchanged. Direct calculation retains the released
50-digit result hash. No source downloads occur in this synthetic probe.

- Regression input: `a86be343957f4baf93818b7a554b6b54ad903c4e35a25b27b6b28206d56d579b`.
- Regression output: `6094e535bf53e645e8aff11404ecd6a6bcdf49eef0b93d783177de71dcc951c9`.
- Replay input: `74097ebf2c103e82dd3f34d132bf16af5e5e86814d4bdd110d22501cce6bb903`.
- Replay output: `cfe1717966d95f4b63bbed97e69d1e9653e608215c03423fe9a74554224b903b`.
- Replay report: `c80102252fc091bda693e29896a11c59c7d6be6f686ffa1b5cbab848cdf6d8f7`.

[Exact implementation CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43007596832)
passes all 12 executed jobs; `fundamental-release-gate` is skipped. The dedicated
`value-investment-agent-361-flow-tests` tmpfs database/container/network are
removed; all 62 pre-existing containers retain their IDs, images and start times.
Commands, output hashes, failure retention, runtime pins and per-model digests
are recorded in `decimal_context_increment` of the accounting checkpoint. Full
generated evidence remains outside Git.

This resolves the reproduced numeric-context defect in engineering validation.
It does not complete real-source numerical valuation, actual independent mapping
review, dated market evidence, caller approval or all 19 full-service gates.

## Microsoft original identity and accounting normalization

Exact implementation `ef61c81d5bd8b8c6109faeabf3fa57298d5e8690` preserves
all earlier checkpoints. It fixes reused original trading-symbol/title pairing
and validates every disambiguating security context (#384). The retained FY2024
Microsoft acceptance time is corrected to `2024-07-30T20:06:22Z` from SEC
submissions metadata digest
`7a94136c40b74495512c975e6bcb62270977e945a855e5f8d8f424b54d08435e`
(#387). It also adds bounded current-lease balance-sheet classification (#388)
and uses the existing canonical highest-XBRL-precision selector for accounting
components (#389). Both preserve the original observations and mapping review
requirements. The composer and valuation equations are unchanged.

Both real originals pass `SecIngestionService.prepare_filing`, strict EFM/DQC
and original identity. FY2023 accession `0000950170-23-035122` has 1,839 facts;
FY2024 accession `0000950170-24-087843` has 1,856 facts. Neither has blocking
findings or parser network attempts. Exact final input/output digests are:

| Evidence | Input digest | Output digest |
| --- | --- | --- |
| FY2023 preparation | `70a06f7410a0c84773453c8c4e3eb69f2da58593943a15caf00154503a7574b8` | `3574443f9a99ec25517e5bcaf1f648f071b46385796803b8e6a7785c4bf751ac` |
| FY2024 preparation | `623973fac4f672d1a5a19bec7d1461dcdfee0b7a6d8ce0ea5b5b110fcd179301` | `77215d4613199e5d1c873611fb9b440ac5144f4ea7f2d615b2492303510982ea` |
| Scoped accounting conversion | `1d0e4df006d1df0172aa10fa61e29349990ec113d46a73fed72dba4c41aaffd0` | `298d76c4ccfa1b3720089b636c6737edbaa672f316f9493f7e01308418c7a7c0` |

The accounting conversion yields 22 provisional period facts for six roles,
including FY2024 current borrowing of USD8,942m from USD6,693m commercial paper
plus USD2,249m current long-term debt. The rounded USD6,700m observation remains
in the original report with the canonical lower-precision rejection reason.
Two prior missing component periods remain unknown. Repeating both strict
preparations and conversion produces identical digests, zero provider requests,
zero new artifacts and `wrote=false`; all 68 existing evidence files retain
their hashes and modification times.

The full 32-role packet has 122 provisional period facts across 24 candidate
roles. Eight remain unknown: depreciation/amortization, complete operating
receivables, contract assets, preferred claims, NCI, convertibles, point-in-time
dilution and other share classes. Packet input
`d55181716c8ceed03f53c20312e1f10143008ce574db128f8a88feb84c76c3ea`;
output `98ac0b44f591859e032ef78f82f6778cf79f3cd66dc29d70d5b2168595bed347`.
Its repeat is unchanged. These proposals establish neither semantic approval
nor complete numerical valuation. No absence or zero was inferred.

Exact PostgreSQL regression: **690 service tests passed / 11 optional skips**,
10 Agent client tests and 17 acceptance-tool tests passed; Ruff/format,
16-source mypy, architecture and diff checks passed. Input
`849aafc104b39bb327c9e65e8867fff5a9b4740df3c39692a985736cab3e4429`;
output `767d9106b25099cf09907995bc2c160296c6a18a9ca5e357c3911eda84c8b278`.
[CI 43013531533](https://github.com/sosodennis/value-investment-agent/actions/runs/43013531533)
passes all 12 executed jobs; `fundamental-release-gate` is skipped. This round's
owned tmpfs PostgreSQL container/network were removed. All 62 baseline
containers retain their IDs, images and start times. Commands, runtime pins,
failures and digests are retained under `microsoft_source_increment` in the
existing accounting checkpoint. Generated source/mapping packets remain outside
Git. #361 and its dependencies remain open pending complete evidence, actual
review, numerical service acceptance, merge and main verification;
`supported_history_threshold` remains null.
Those remain the next work. #361/#385/#386 remain open until accepted delivery
and merge/main verification; PR #370 remains draft and the history threshold null.


## #391 dated disclosures and #392 canonical PostgreSQL fact persistence

Exact implementation `dea88ad41d006244f63b762f268618a2e5203ede` retains all prior WIP commits. `ac34044b`
adds typed dated comparative narrative components to the existing accounting
normalizer; `dea88ad4` fixes a real-source backup rejection by using the same
canonical fact digest for direct and transactional PostgreSQL publication.
The first complete payload and source/PIT annotations remain retained. Different
selection views reuse source identity; changed source/value still rejects.
Forecast/calculator equations and composer v3 remain unchanged.

Exact regression: **740 service tests passed / 11 optional skips**, 10 Agent
client tests and 17 acceptance-tool tests passed. Ruff/format, 17-source mypy,
architecture and diff checks pass. Regression input `c7a47972bcc4c473518c5637a0c79c500e4920c4d1b06ab52089d2f39597ca90`;
output `4e69f752728a73f8ae50096d6a1ac4bf4fe33ce04f5d9183544b1d02315aeec7`. [CI 43020075601](https://github.com/sosodennis/value-investment-agent/actions/runs/43020075601) passes all 12
executed jobs; `fundamental-release-gate` is skipped.

The two Microsoft originals again pass strict EFM/DQC and original identity,
with 1,839 / 1,856 facts and zero provider requests. The new proposal preserves
exact original HTML, date/amount/unit/scale spans and reported precision. It
combines numeric trade receivables with separately disclosed server-component
receivables while excluding adjacent financing balances: 2022 USD50.361bn,
2023 USD57.888bn and 2024 USD67.424bn. The comparative 2023 amount agrees across
both originals. All four resulting observations remain **provisional** and
require actual semantic review for date association, completeness and overlap.

Real-source persistence boundary acceptance stores four provisional facts,
two mappings, two original snapshots and 12 content objects. After closing and
reopening the store, every exact source/fact payload is retrieved. A digest-checked
backup restores to a separate empty store; repeated publication, export and
restore add no rows or artifacts. This is metadata/source boundary evidence;
there is no active release, prepared valuation or numerical calculator artifact.
The valid selected-view regression reproduces the original canonical-digest
backup failure against archived `ac34044b` code before the owning fix.

Both strict parser executions, accounting conversions, full role packet and
persistence sequence are repeated at the same commit/runtime. All input/output
digests match, `wrote=false`, no provider downloads occur, and all **190** retained
evidence files keep their hashes and mtimes. The dedicated tmpfs test project
`value-investment-agent-361-flow-tests` on `127.0.0.1:18665` is removed; all 62
baseline containers retain their ID/image/start time. Only this project's
disposable fixture databases are removed; retained originals, proposal packets
and verified backup remain outside Docker and Git.

The full packet now has **126 provisional period facts / 25 candidate roles**.
Seven roles remain unknown: depreciation/amortization, contract assets, preferred
claims, NCI, convertibles, point-in-time dilution and other economic share classes.
Neither mappings nor policy have actual independent approval; no trusted release,
caller approval, real numerical valuation, complete 19-gate service acceptance or
history-threshold sufficiency is claimed. `supported_history_threshold=null`.
#361 / #370 / #391 / #392 and dependencies stay open. Continue with source-bound
role/policy evidence, then review, full-flow validation, merge and main verification.

Compact command receipts, digests and retained failure evidence are in
`issue-361-accounting-checkpoint.json` under
`dated_disclosure_persistence_increment` (checkpoint
`a5a8ba070ba5b38f44e36d229dbdade7e6de017a704d0966032e3a5ed7f8ff9e`). Generated source/mapping/backup corpus stays
outside this PR. The separate #390/#393 checkpoint is a research integration
reference pinned to its own earlier baseline; it is not silently merged here.
