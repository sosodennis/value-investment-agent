# Fundamental parser actions

Parser actions reuse deterministic parsing work. They do not grant source-use
permission, approve mappings, authorize releases or approve calculator inputs.
Those owners continue to apply their current policies independently.

## First protocol

`sec-parser-action-input-v1` deliberately includes the delivery revision. The
owner derives the key by reading actual staged files, captured normalization
inputs, implementation, controlled Linux image runtime, complete taxonomy and
plugin trees, DQC rules/catalogs, parser profile and report schema. Unknown
dependency closure falls back to ordinary parsing. A supplied digest, path,
mtime or `validated` flag cannot create a reuse decision.

The initial runtime closure conservatively covers `/app` and `/usr`, resolved
native/image links, Python identity, deterministic worker import paths, loader
configuration and relevant environment. Custom external loader, SSL or bytecode
configuration is unsupported. Required source/resource traversal propagates
listing errors. For broad image traversal only, an unlistable directory can be
excluded when effective-credential access checks also deny search/traversal;
its access metadata and credentials enter the identity. Searchable but
unlistable directories make the action uncacheable. No taxonomy test directory
is removed. This conservative protocol is not cross-delivery build identity.

Each exact key uses the existing PostgreSQL ingestion advisory lock. A
successful attempt stores immutable report bytes and a result binding that
report to its full action request before atomically updating the discoverability
index. Incomplete attempts never publish an index entry. Start and terminal
failure evidence remain available; process interruption leaves a recoverable
start. Missing, corrupt or invalid indexed evidence causes a fresh parse.

The report body retains its real `parsed_at` and original parser path. Separate
use attestations record reuse time, delivery revision and the selected result.
The original issuer owner continues its existing canonical path/time/profile
transformation. Independent readers replay that transformation from the verified
body rather than comparing a raw report directly to an issuer report.

## Source and publication boundaries

Normalized and archive actions remain distinct. Ingestion still executes or
authenticates both required sides and compares fact/finding semantics before
admission. Both comparisons use the same filing-date DQC applicability context.
One completed side can survive interruption; it alone cannot establish complete
source integrity.

The result and body are registered retained artifacts. Their references travel
with mapping and release evidence, rather than remaining private producer state.
Preparation, mapping replay and each independent release verifier authenticate
their own evidence. Within one mapping operation a bounded report cache shares
the checked result; current metadata is checked on each use. Signing and
successful output boundaries rewalk consumed references, authenticate bytes and
recheck all metadata after I/O, including references whose cached checks were
evicted. Producer scopes never substitute for independent verifier checks.

The additive `004_parser_actions.sql` migration creates the action index and
advertises `sec-parser-actions-v1`. Stores without that capability use ordinary
parsing. Backup/restore includes the index, immutable results, registered report
artifacts and source content; restored results still pass the same content and
current-metadata checks before reuse.

## Validation status

The first evidence-context increment has real numerical measurements in
`fundamental-evidence-reuse-acceptance.md`. Parser-action implementation and
focused boundary/PG recovery tests are a separate increment. Real parser hit
counts, end-to-end numerical timing, restart/recovery acceptance and a complete
cross-delivery build protocol must be established independently; this design
description does not claim those outcomes.

Agent skill review covered `agent-implementation-extractor`,
`agent-debug-review-playbook` and `architecture-standard-enforcer`. No agent
topology, graph/state contract, capability ownership or cross-agent import changed;
their guidance remains applicable and no skill change was needed.

## Measured delivery-scoped action checkpoint

Exact implementation `3d6153e7a8b4dd1208b6ed169ea28dec003391bb` completed
the real SEC-enabled MSFT numerical flow, deployment-authorized exact-input
caller, calculator, persistence and authenticated API/provenance retrieval.
Six normalized/archive bodies each had one miss and one reuse; the retained
content hash and genuine original `parsed_at` matched on reuse.

This increment **regressed warm replay**. Five alternating unprofiled successful
complete runs per side, under the same one-CPU/3-GiB issue-owned runtime:

| Metric | Operation context `7713fb26` | Parser actions `3d6153e7` |
| --- | --- | --- |
| Wall median (seconds) | 39.75097 | 57.34497 |
| Wall range (seconds) | 39.09325–40.02983 | 57.04024–58.08314 |
| CPU median (seconds) | 36.43208 | 53.68925 |
| CPU range (seconds) | 36.06742–36.53301 | 53.40302–54.33619 |

All ten runs calculated successfully, retrieved equal numerical results and
provenance through authenticated API, retained stable applicable artifacts
within each version, reported lineage/execution `wrote=false`, and left domain
row counts unchanged. Full receipts include sampled memory and host load.
Existing-source first preparation was one unprofiled 703.3000-second sample
(CPU 633.1909 seconds, sampled peak 2,853,634,048 bytes); it does not establish
improvement over the prior 664.5843-second sample. New-original execution has
not been measured in this checkpoint.

Separate attribution, excluded from timings, found nine action checks and nine
`evaluate_original_issuer` calls across the producer and independent canary.
Those calls rebuilt full issuer claims from raw normalized reports even after
the consumer validated its original claim. Nested durations are not summed.
The next correction shares the consumer's existing bounded claim checks and
compares the exact existing v1 canonical report transformation separately.
It preserves full claim validation, raw-body equivalence, live metadata/content
checks, independent scopes and all original canonical/digest algorithms.
Its performance remains unmeasured until a new exact-image run.

Commands: `benchmark_parser_warm.py` and `run_diagnostics_parser.py`, each exit
zero, in the ignored `.audit/issue-445-evidence-reuse/` directory. First-preparation
receipt, parser-action body/time summary, API receipt, per-run outputs and failed
startup attempts remain there outside Git. MSFT remains provisional uncalibrated
what-if; the history threshold remains null. V1 still includes delivery revision;
cross-delivery identity, final restart/restore/refusal acceptance and merge
verification remain incomplete.

Evidence SHA-256:

- `stage2-final-benchmark.json`: `101b2ebf62d39e909fbeaa3d555a39eaa3ff1b1733388ffeba05a5761b7e15be`.
- `parser-3d6153e7-first-receipt.json`: `85fb3473581dbf5ecd90dab8a24a40bbeeba7de526994789c09be68f43c00a3f`.
- `parser-3d6153e7-first-actions.json`: `a53fc9ef58ec7b0c0cbc4fd7ef88e8763bf51af97ab57912070e3adfa866e526`.
