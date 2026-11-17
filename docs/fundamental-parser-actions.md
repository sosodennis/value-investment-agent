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

## Claim-verification correction checkpoint

Exact implementation `21514a513d44a71f576e6c5f0d2a2e9a2ccc543f` completed
one existing-source first preparation in675.2820 seconds (CPU605.1935 seconds,
sampled peak2,923,130,880 bytes), with equal numerical results and authenticated
API provenance. This is a single differing-store sample, not a controlled
first-preparation improvement claim.

Five alternating unprofiled successful full warm numerical/API runs per side
compared this correction with `7713fb26`: wall median40.07213→50.63608 seconds,
ranges39.76563–40.99818 /49.59784–51.60319; CPU median36.77068→46.91078 seconds,
ranges36.59630–37.73863 /46.04335–47.50688. All ten runs preserved numerical
equality, within-version applicable artifact equality, wrote=false, unchanged
domain row counts and authenticated result/provenance retrieval. The correction
reduces the preceding parser-action regression, but remains slower than the
operation-context version without action evidence.

Final focused checks:271 passed (55.07 seconds), mypy1.19.1 on four changed
source files, pinned Ruff/format, architecture guard and diff check passed.
Independent read-only review found no remaining concrete correction blocker.
Three deliberately malformed model-copy cases emit expected serializer warnings.
Required CI passed, including the service release gate; legacy
fundamental-release-gate skipped and is not treated as a pass. This checkpoint
still does not establish cross-delivery reuse or final restart/restore delivery.

Command: `benchmark_claim_warm.py`, exit0. Raw originals, per-run receipts,
profiles, row counts, limits/load samples, failures and API evidence remain in
the ignored issue audit directory. The first run's raw stdout and receipt are
`claim-21514a51-first.*`; the five-pair output is `claim-final-benchmark.json`.

- `claim-final-benchmark.json` SHA-256: `cd8ea564bd8bd80a2d1df8c8b488549bb9ec80118a9f46f996034e7ca20c9273`.
- `claim-21514a51-first-receipt.json` SHA-256: `0a6daad2af21dcc13f4ee170c8b3b028189285ee11ab681e6a0105efd156a4c3`.

## Cross-delivery protocol

The additive V2 action separates the delivery revision from an owner-computed
`sec-parser-build-v1`. V1 identities and readers retain their original canonical
meaning. V2 still hashes the complete first-party implementation and controlled
image Python/native/runtime trees, output schema, staged DTS/IXDS and normalized
bytes, captured normalization dependencies, taxonomy/plugins/rules/catalogs and
validation profile. This is conservative invalidation, not a minimal parser
closure. No taxonomy directories or large text evidence are removed.

V2 requires a non-root Linux image whose root was read-only before Python
started, no effective/permitted/ambient capabilities and no-new-privileges.
The optional `compose/verification/docker-compose.parser-actions.yml` supplies
that boundary and project-owned writable scratch. The owner reads kernel mount
and credential state. The overlay disables Docker's injected init helper mount
inside `/usr`; Uvicorn receives signals directly as PID 1, while parser and
native-inspection owners explicitly wait for their subprocesses. Restart and
interruption acceptance must exercise this deployment configuration. Dependencies
on descendant mounts cannot establish the image build. Source/resource mounts
are still separately read and hashed.
Each independent operation computes its own expected build and rechecks the
configuration after slow I/O and before successful output. A producer's cached
validation or approval is never sufficient for a consumer.

Native admission inspects ELF architecture, executable interpreter, explicit
library search paths, loader-cache destinations and resolved linked libraries.
Only fixed hashed image paths can support an unresolved optional library.
Foreign-architecture bundled libraries remain byte-hashed. External loader,
XML/SGML catalog, conversion/locale/timezone and glibc-tunable overrides are
unsupported; unknown formats or closures fall back to delivery-scoped V1 or
ordinary parsing. V2 evidence consumers refuse an unestablished current build.
The implementation intentionally supports the controlled image rather than
attempting a general native-loader framework.

A deterministic retained `sec-parser-action-delivery-v2` record binds the
current delivery/build to the exact action, result and body. The V2 report
marker references this record. Fresh `sec-parser-action-use-v2` audit events
separately retain genuine use time and hit/miss, referencing that binding.
Thus same-delivery reuses preserve report/issuer/mapping identity; new delivery
bindings remain distinguishable while the body keeps its original `parsed_at`.
Neither record grants source-use permission or exact-input approval. Existing
PostgreSQL exact-key locking, recoverable attempts and atomic result indexing
remain the only parser action coordination mechanism.

Pre-deployment checks on this increment: 297 owner/integration tests passed,
two resource-dependent cases skipped; isolated PostgreSQL V1/V2 single-flight,
new-owner and empty-store recovery are included. Types on 13 changed source
files, pinned Ruff/format, architecture guard and diff check passed. Independent
read-only review found and corrected native/catalog closure, final-check ordering
and timestamp identity drift; it did not execute tests or runtime. A WIP image
probe established the immutable build in about nine seconds; that is a local
capability probe, not an end-to-end performance claim. Full exact-image numerical,
parser-hit, restart/restore and alternating timing acceptance remain pending.

## Stable computation and exact execution identities

The next identity revision separates equivalent computation from retained proof:

- `sec-parser-action-input-v3` uses resource roles, logical filenames, taxonomy
  namespaces and exact hashes, so relocating identical mounted resources leaves
  the work key unchanged. Immutable build and full source/resource closure remain
  required. V1 fallback and existing V2 readers keep their original meanings.
- Raw result artifacts retain genuine parser timestamps, paths and exact bytes.
  Rebuilding a missing body can produce a different execution artifact even when
  its work key and semantic output match. Delivery/use attestations still name
  that exact execution; they are never rewritten to imitate an earlier run.
- `original-issuer-operating-v2` retains the complete ordered raw validation
  evidence separately from deterministic computation markers, normalizes catalog
  paths and equivalent UTC instants, and retains full facts, finding text,
  severities, validation profile and source dependencies. Both computation markers
  bind the full normalized report and their respective action keys. An archive
  marker is not a hash of the archive report's complete output. The archive body
  remains independently read, validated and compared under the existing dual-side
  semantic rules. The original exact evidence binds both bodies.
- `fundamental.mapping-computation.v1` composes a full report projection digest
  with small mapping parameters and policy identity. The existing bounded
  `MappingInputDigests` context computes the projection once per retained report
  in each operation. It authorizes no admission, release or approval. It also
  accompanies abstentions. Mapping signatures bind this additional identity and
  the unchanged exact request digest. Missing or altered fingerprints fail replay.

A reparse may preserve domain mapping/computation identities while changing exact
input, proof and approval artifacts. Fixed retained-input replays still require
exact applicable digests and `wrote=false`; cross-execution evidence equality is
not claimed. Legacy v1 proof digests are preserved, including their previous JSON
handling of timezone offsets. V1 originals and raw parser bodies reject the new
representations; new originals reject missing raw action closure and unsupported
computation versions. Ingestion rebuilds mapped facts from the report actually
admitted by the mapping owner, while source integrity retains raw execution proof.

The deployed `c2077b8b` cold preparation failed at 902.720909 seconds (830.260509
CPU seconds), with six parser misses and six hits. This is counterevidence to
whole-flow performance acceptance, despite successful parser reuse. Sampled memory
peaked at 2,914,050,048 bytes. Raw receipt and failure output remain outside Git
in `.audit/issue-445-evidence-reuse/build-c2077b8b-first.*`. Identity correctness
checks do not resolve or conceal this timeout; diagnostic attribution and a fresh
exact-image successful numerical/API run remain required.

### Runtime closure ancestry correction

A diagnostic profile of deployed `c2077b8b` exposed repeated creation of the same
`Path.parents` sequence for every mount predicate at each image node. The owner
now computes the resolved node's ancestor set once. It retains all mount,
cycle/dynamic-path, file-content, directory and native closure checks, producing
byte-identical runtime digests in the controlled image.

Five alternating algorithm-only runs on the same read-only image, one CPU/1GiB,
measured runtime-identity wall median8.14549→4.77925 seconds (ranges7.89370–8.43554 /
4.50180–4.84643). All ten digests matched; peak RSS97,356KiB. This is a helper
measurement with full native scanning; it does not establish whole-flow speed or
resolve repeated independent verification costs. The driver and raw output remain
outside Git: `benchmark_build_ancestry.py`, `build-ancestry-five-pairs.jsonl`
(SHA-256 `759874b47cba274e2d22423717275a612d336e6726c56570df1dc89daecc94f7`).
