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

## Runtime Boundaries (Current)
`fundamental_analysis` workflow nodes are orchestration-only and delegate to
the agent package:

1. Domain:
   - `src/agents/fundamental/domain/model_selection.py`
   - `src/agents/fundamental/domain/valuation/**`
2. Data clients:
   - `src/agents/fundamental/data/clients/sec_xbrl/**`
   - (Ticker resolution/search clients now live under `src/agents/intent/data/`)
3. Application entrypoint:
   - `src/agents/fundamental/application/orchestrator.py`

The workflow layer should not contain a local `tools/` package anymore.
