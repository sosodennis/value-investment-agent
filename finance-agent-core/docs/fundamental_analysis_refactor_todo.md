# Fundamental Analysis Refactor TODO

Last updated: 2026-02-10

## Scope
- Keep path `finance-agent-core/src/workflow/nodes/fundamental_analysis`
- Move engine/skills/sec_xbrl/registry into `fundamental_analysis/tools`
- Remove legacy executor/auditor/calculator subgraphs and related tests/frontend
- Keep TraceableField/Provenance
- Store reports via artifact id in state (rename field for clarity)
- Update README

## Decisions
- Rename `latest_report_id` -> `financial_reports_artifact_id`

## Checklist
- [x] Create new tools layout under `fundamental_analysis/tools` (sec_xbrl, valuation, registry, report_helpers)
- [x] Move SEC/XBRL modules to `tools/sec_xbrl` and update imports
- [x] Move engine to `tools/valuation/engine` and update imports
- [x] Move skills to `tools/valuation/skills` and update imports
- [x] Move SkillRegistry to `tools/valuation/registry.py` and update imports
- [x] Move node helpers to `tools/report_helpers.py` and update usage
- [x] Rename state field to `financial_reports_artifact_id` and update all references
- [x] Update fundamental_analysis nodes to read reports via artifact id
- [x] Remove legacy executor/auditor/calculator subgraphs and tests
- [x] Update frontend to remove executor/auditor/calculator configs and fallbacks
- [x] Update fundamental_analysis README
- [x] Sanity-check import graph to avoid circular dependencies

## Progress Log
- [ ] 2026-02-10: Core module moves + state rename + legacy cleanup completed; controlled assumptions added
