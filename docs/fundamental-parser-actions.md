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
