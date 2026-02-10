# Fundamental Analysis Node

## Overview
The Fundamental Analysis subgraph retrieves SEC XBRL financials, selects an
appropriate valuation model, and runs deterministic valuation calculations.

## Flow
1. **financial_health**: Fetch SEC XBRL reports and store them in the artifact
   store. Emits a lightweight preview artifact.
2. **model_selection**: Loads reports from the artifact id, selects a valuation
   model, and saves a full report artifact (includes reasoning + reports).
3. **calculation**: Builds model parameters from reports and runs the
   deterministic valuation engine.

## State Contract
The subgraph does **not** store raw financial reports in state. It only stores
the artifact pointer:
- `financial_reports_artifact_id`: Artifact id pointing to stored financial
  reports (either raw list or full report payload).

## Controlled Assumptions (Temporary)
Some valuation inputs (e.g., WACC, terminal growth, missing D&A rate) may use
controlled defaults to keep preview flows unblocked. **This is a temporary
measure and is planned to be refactored** into a stricter, enterprise-grade
assumption workflow with explicit approval and audit controls.

## Tools Layout
```
fundamental_analysis/tools/
  sec_xbrl/        # SEC XBRL extraction + mapping + models + factory + utils
  valuation/       # Skill registry, param builder, engine, skills
  model_selection.py
  report_helpers.py
  tickers.py
  profiles.py
  web_search.py
```
