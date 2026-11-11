# Fundamental Service owner checks for #361

## Current exact source and Docker verification

Implementation `ea99e6f6cbb52bf58d54e94ebbf88faa707e12e1` fixes the observed
truncated HTTP transfer retry boundary. Three real chunked-transfer regressions
fail before the fix. The corrected source/capture suite passes 26 tests and
proves bounded retries, closed responses, no partial evidence, exact successful
bytes and unchanged retained reuse. The final exact-commit owner suite passes
515 tests/9 skipped, including PostgreSQL; 28 changed service source/script
files pass dependency-complete mypy. The other checks below pass again.
[Current verification](issue-361-owner-ci-v1/verification/c3dc1f71cb6edd181a8def3a9b04be507b40790e2bc3b08cf88c08b17aebdb42.json.gz)
retains input/output digests and command results; full command ledger
`881be8b5c39c8f47694a28bc1c63016857f43fd816348ba5364e4bd2b9d22e4a`.

[GitHub CI 42854301038](https://github.com/sosodennis/value-investment-agent/actions/runs/42854301038)
passed all 12 executed jobs. The service owner job passed 514 tests/10 optional
checks skipped, 50 changed Python formatting checks and all 28 source types.
The local historical fixture check accounts for the additional local test;
the CI fixture limitation is explicit. The manual legacy release job was
skipped and its earlier #372 failure is not superseded by these contract checks.

Image `sha256:2ed38523a52eb1de6587652091ec82274300d68aa3d89188176eeb1509320615`
is healthy in the separate `value-investment-agent-361-candidate-contracts`
Compose project, with ports18663/18664, its own network and named volumes.
All 54 installed source files match the exact implementation. SEC identity
capability is configured. Two actual preflights produced the same input
`a2f65560f1357924e2795f2e6d12fc5f4b5ad2a7684f5c1e91fd27213bca02fa`
and output `630c15007bdd73a2bc5e3191559df3f4b763a14d177fdf4a4bc3c7b366d8470e`;
the second report returned `wrote=false`. This proves the service preflight,
not full cohort replay. [Current runtime](issue-361-runtime.json) stays BLOCKED.

The [original diagnostic runtime](issue-361-original-runtime.json) is separately
retained. Its container continues unchanged with the frozen4c source/image,
ports18661/18662 and its original project/storage. The newer image build and
candidate acceptance did not interrupt or recreate it. Both projects belong
only to #361 and remain retained while the issue is open.

## Earlier owner checkpoint

Exact implementation: `26328170e3ead4b2b186111539aca0cd5cf36570`.
[Verification artifact](issue-361-owner-ci-v1/verification/9e5066c1227812491c3113a4666f837d6a8a3f6be8a907a90cae71c900427c9f.json.gz)
records the frozen command results, runtime pins and content-addressed executor.
The full command ledger is
`2ccdd5d26441ee792ecef1624a1f326bd72b9372f4fe9a54409070e62555ee15`.
Each check records its commit, command, input digest, output digest and exit code.

The configured owner suite passed **512 tests**, including PostgreSQL, with
**9 optional checks skipped**. The PostgreSQL suite separately passed 17 tests;
these are included in the 512, not additional independent observations.
Tests use the issue-owned `issue361_ci_contract` database at port 18662. They
do not run destructive schema tests against the diagnostic `fundamental` database.
Twenty acceptance-tool tests also passed.

All 27 changed service source/script files pass mypy 1.19.1 with frozen service
dependencies installed and `MYPYPATH=finance-agent-core`. The earlier
`uvx mypy --ignore-missing-imports` passes lacked these dependencies and do not
establish dependency-complete type acceptance. The initial 123-error probe and
subsequent diagnostics are retained with their working-tree limitations.
Service Ruff 0.14.10, changed-file formatting, architecture guard, generated
contracts, tooling types/lint, Bash syntax and `git diff --check` all passed.
Preparation outputs match the retained pre-type baseline. Policy and model
definitions are byte-identical, digest
`e33ea7474f604c514be4d0236d9594fbf163b53b54525f89e9733b200490b8d5`.

The existing project signer verifies both proposal seals. Key initialization
returned `key_wrote=false`, identity `wrote=false`, with unchanged key and public
identity mtimes. No independent approval is asserted by these signatures.

The new owner CI job uses frozen service dependencies and an ephemeral
PostgreSQL database. Its actual GitHub result must be inspected separately;
local success does not establish CI success. The older manual release run
`42843599517` failed on unchanged baseline release inputs: stale policy evidence,
insufficient monitoring observations, and an incomplete live cohort. Those
owning requirements are recorded in [#372](https://github.com/sosodennis/value-investment-agent/issues/372).

The running Docker diagnostic source remains
`4c65950b1d31797d0cb50a69d56674e586f3c3fc`; it is not this host implementation.
Its first controller stopped after 371 retained observations because a chunked
HTTP response raised `http.client.IncompleteRead`. This is an acquisition
interruption, not a missing financial fact. The same exact command, source,
runtime pins and output directory resumed using the retained results. Preserve
the failed controller log and the completed resume/repeat results separately.

Full 589-filing diagnostic repeat, independently reviewed historical identities,
mappings, policies/releases and actual #352 composer replay remain incomplete.
Both `supported_history_threshold` values stay null, affected valuations remain
provisional or abstain, PR #370 stays draft and #361 remains open.
