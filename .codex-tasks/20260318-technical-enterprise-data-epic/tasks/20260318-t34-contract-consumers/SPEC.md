# T34 Specification

## Goal
Align technical full-report schema and frontend contract consumers around the new enterprise evidence and alert semantics.

## Slice 1 Scope
- Add report-level typed `quality_summary` and `alert_readout` fields.
- Load alerts artifact into semantic projection artifacts and project deterministic report summaries from backend application logic.
- Align frontend report types/parser and generated API contract in the same slice.

## Non-Goals
- Do not add new alert policies.
- Do not change frontend UI rendering yet.
- Do not expand observability dashboards in this slice.
