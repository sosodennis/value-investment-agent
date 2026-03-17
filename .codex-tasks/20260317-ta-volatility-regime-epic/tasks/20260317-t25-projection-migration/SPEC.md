# Task Spec: T25 Projection Migration for Regime and Structure Evidence

## Objective
Carry deterministic regime and VP-lite evidence through semantic interpretation inputs and the technical full report so downstream consumers read artifact-backed summaries instead of only raw artifact references.

## Scope
- Extend semantic pipeline contracts to load the regime pack alongside pattern, fusion, and scorecard artifacts.
- Project `regime_summary`, `volume_profile_summary`, and `structure_confluence_summary` into interpretation setup context and full report payloads.
- Update consumer-facing tests in the same slice to keep the output contract migration atomic.

## Non-goals
- Rework regime classification policy or signal-fusion weighting.
- Introduce UI redesign beyond the backend/interface contracts touched by the new summaries.
- Change VP-lite calculation semantics in this slice.
