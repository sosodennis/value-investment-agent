# Issue 386: deterministic Decimal context

Fundamental Service owns this correction. The existing preparation, metrics,
override, validation, calculator, uncertainty and independent challenger
boundaries use one fixed local Decimal context and restore caller state on
success or refusal. No financial formula, wire contract or model identity is
changed. The released numerical policy remains50 digits/HALF_EVEN; the target
document's contradictory34-digit entry is reconciled with that existing policy.
No #385 lease change, #361 accounting/provider contract or generated research
artifact is included. Estimates and history threshold decisions are unchanged.

Implementation checkpoint `26da12a9cbc0c212c1b5e77181f1962d91aa1afb`
starts at main `17975bd1b5a5195d0dcaab9ba0e4c5808434424e`. Checkpoint
`eb59fce48df49c90c6efe5aee189f88a994b51f0` adds the two-line #430
PostgreSQL fixture correction. The original main has both failures too:
the fixture lacks the filing year/form scope already required by production,
causing403 to become500 and preventing the50-contender test from running.
Production fallback or assertion removal is unnecessary. Linked blocker #430
records the root cause and reproducible isolated command.

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-independent-review-evidence/386-main`.
The frozen Python environment there is `venv/bin/python`, CPython3.11.15,
Pydantic2.14.2, Arelle2.47.4. Every receipt contains commands, exact source SHA,
input/output digests and exit codes. Generated evidence remains outside Git.

## Root cause and released output

On pristine main one input digest
`816f8a4f2faa2261b6481c334564875a0d8e29301b676665ca957edf44fed3ca`
produces three result digests under different ambient contexts. Intended50-digit
output is `113911627cf76c090aeffe0a4c3731cb915def7391ae768493343906dc7a38a1`.
Before production edits the copied behavioral regression fails3 cases,
including `decimal.Rounded` under trapping context. Failing receipt
`2fd109644626589bd51496d2e74fbf398e95d50aa5051a1c9265d1064f1c8e5c`.
All26 Decimal tests now pass, covering worker threads, preparation, metrics,
override, MC invalid draws/refusals, validators, challenger and caller context
restoration. Independent fresh-process old-main/new-code50-digit comparison
of both preparations, calculation and24-draw seeded MC is byte-identical:
`6f7c674fe1fd34143ba7f1dd6bf84710669bfbdb86d698539c00b1769915ee89`.
Independent parity receipt `7acc9b776a797f6d01335f0d40ad0328bc95c6e3d40ee8757439ff7b758b6fdc`
is in the external `issue-376-research-evidence/cleanup-review-386` directory.
Its first strict-schema driver failure is retained; only its Decimal inputs
were corrected, without loosening production validation.

## Exact eb59fce4 checks

`FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:19637/fundamental
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=fundamental-service/src:finance-agent-core
$PY -B -m pytest -q fundamental-service/tests -p no:cacheprovider` passes359
tests,8 explicit optional parser-resource skips, exit0. PostgreSQL tests run.
Receipt `0753bd0481eb14295460fd1ff06ce487d4dc5613c6f83bf94b110aac15486f4c`,
input `6f3f6be152373e9630e0a07586859a21a25c99ffbc868649764cc353aa196b08`,
output `60edfec82bef4062aab5f0215196a9b5c40aa8da0a811778e3de1ff9a1888a8b`.
Original PostgreSQL failures are retained in receipt `c596d610...`; pristine
main reproduction is `e2e47d49d927794a596c020a6c2c83a5c80fc13a26efff179ff6c476a1865a6a`.

Changed11 Python files pass Ruff0.14.10/format and actual hooks; both guards
and `git diff --check` pass. Dependency-aware mypy1.19.1 uses the actual frozen
Service interpreter, follows imports silently and suppresses only untyped
external packages. Five numeric modules pass cleanly. The eight-module check
still reports274 legacy diagnostics in contracts/policies/preparation; it is
explicitly exit1, not a full type pass. The same command on pristine main has370.
Source-line mapping proves every current diagnostic belongs to an unchanged
line and identical baseline message:0 introduced/changed-line diagnostics,
96 removed. Receipt
`ad20648850fa114d01156201b68641a8053993fc666478853c4820363354f561`,
input `db4b892a23f0a3b40f74b143f268373c12cc4c17bac1543be15e9317af3056aa`,
output `946e8b9d9444398aa33729032b31babf4f23461f49f0f991d89ab912d03e9592`.
No project diagnostic is ignored or converted into a pass.

## Isolated service, repeat and recovery

Project `value-investment-agent-386-decimal-main`, unique host ports19636/19637,
network `10.203.86.0/28` (checked against all37 existing Docker networks), own
PostgreSQL/content named volumes. Automatic address-pool exhaustion was retained
as a startup failure, then corrected with explicit nonoverlapping IPAM; no
daemon setting or existing network was changed. Runtime-only `compose.json`
and `runtime.env` live under the external evidence root. Config SHA256
`f158bc9060e277021de4d4505449899ede2ac039f9479d0d8ec969acbaa801cf`,
env SHA256 `537a79e9f03327d132336ec6052d13564c2fe1850397b893904f0c459f5afa7f`.
The standalone config derives the existing operations Compose service set.
Exact image `sha256:4301a510817240e873c9e10cd71a32f97345d9414f96bf461a6d5ad8c10a589c`
records the source SHA; all baked Service Python hashes match the checkout.
Compose config, build, healthy PostgreSQL/service and HTTP `/readyz` pass.
No browser workflow or SEC identity-resolution acceptance is claimed.

`verify_numeric_runtime.py` calls real authenticated HTTP calculation endpoints
for both released models,24-draw seeded MC and forged-digest refusal. Its signed
synthetic release uses only public development fixture keys in this disposable
database; it is not accounting/mapping approval or real-issuer evidence. Repeat
requests leave every PostgreSQL table and content bytes/sizes/mtimes identical.
Restarting both service and PostgreSQL reproduces the same full receipt:
`f2ced34a6e0f7e4338b4beace9f74bb98bdebc5a13a8f46e86fa19b1708a57f6`,
input `c2a487d5405d5dcc83f92367ade9a08c98a848ae4068ee60e93e8792c32775e0`,
output `8bb822434bb1177494b3e62736af9fbfa94105ccf09347e7e2d1f07a94ce0247`.
The forged digest returns400/invalid_request at the strict transport boundary.
The first driver expected422; its failure receipt `873261f5...` is retained;
only that external expectation was corrected.

`verify_recovery.py` verifies resource ownership, records reset scope, stops
the service, hashes/preserves its database dump and POSIX content archive,
restores the database transactionally, removes only backed-up/hash-matched
synthetic content files, restores them and reruns HTTP acceptance. Result and
all database/content inventories reproduce the same receipt above. Recovery
receipt `ffb5017bcd04bab7a5c8bd83d3df6546840c4b6bcd2e045d14d32339a49441b3`;
command `5945fc57ac92241666c874216bea4e97036d907d6efb0557e918bba6d1348612`,
input `b709cecef17a88e9686b453feba49dbe91315745c5883692f975ee430bd94bfe`,
output `b24f0dd32fe5344fef923f49c5c8b25f697ed2e703c7e7a098abf9aaa5551d44`.
Backup digests are `ae0d6688c14e701b1e11bfff82cd51e0a8ff1fe3d22aa583e5de84e1779614e4`
and `87bb8cfa476fc5611c1a969e068b57e9a499eb3dff6223c3ada24ed57ad1d4e7`.

Next: ordinary-merge latest reviewed main, rerun affected exact-commit checks,
record final receipts, obtain independent PR review/CI, serially merge and verify
the main merge commit. Only then close #386/#430 and clean owned resources.
#361/#376/#377 remain open, history underpowered and threshold null.
