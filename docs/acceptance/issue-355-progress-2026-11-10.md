# Issue #355 progress: opt-in forward-evidence reference

Status: WIP checkpoint. This document records the implementation boundary and
the evidence still required before issue acceptance.

## Current state

- Branch: `codex/issue-355-forward-reference`
- Base commit: `e761e13577fb0e50cf611edd0ee2386e90ed360a`
- Normal Fundamental valuation remains the only default path. Search and LLM
  calls are not part of the normal request flow.
- The optional reference will use an explicit Fundamental action route. Agent
  Core owns request orchestration and provider calls; Fundamental Service owns
  claim validation, quality disposition, source/licensing provenance, and
  application of a selected value.

## Planned contract

1. A reference request identifies the issuer, model, material evidence field,
   and the automatic preparation digest. It is rejected unless the caller has
   explicitly opted in.
2. The response is a separate forward-looking evidence layer. Each numeric
   claim includes the issuer, metric, value, unit, fiscal period, publication
   and retrieval timestamps, source identity, retained passage, content hash,
   extraction method, quality/conflict status, and license metadata.
3. Unsupported, stale, mismatched-period, conflicting, or unlicensed claims
   are excluded or surfaced with a typed reason. Search results and LLM output
   alone are never treated as evidence.
4. Research does not change a valuation. Applying one claim calls the existing
   Fundamental override path with the automatic preparation and a manual
   provenance record that retains the selected reference. A new input digest
   and recalculation are required.

## Checks still required

- Contract and domain tests for valid claims, rejection reasons, conflicts,
  licensing, freshness, and digest-bound application.
- Agent Core tests proving no optional-provider call on the normal path,
  explicit opt-in orchestration, provider failure, and bounded resource use.
- Browser tests for the explicit Fundamental action, evidence display, and
  selected application.
- Isolated Docker/service-backed acceptance with the #355 Compose project,
  followed by exact-commit CI and PR evidence.

## Known limitation

No production provider calls are enabled by default. Resource budgets remain a
measured acceptance item; this checkpoint does not claim #355 is verified.
