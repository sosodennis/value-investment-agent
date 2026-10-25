# Contracts

This folder contains generated cross-stack contracts used by both backend and frontend.

## Files

1. `openapi.json`: Exported from FastAPI (`finance-agent-core/api/server.py`).
2. `fixtures/manifest.json`: Index of supported durable activity contract versions.
3. `workflow-activity-v1.schema.json`: Cross-language JSON Schema for `workflow.activity` events, activities, and snapshots.
4. `fixtures/workflow-activity-v1.json`: Shared activity behavior fixtures consumed by backend and frontend tests.

## Generate

From repository root:

```bash
bash scripts/generate-contracts.sh
```

This exports backend OpenAPI and regenerates frontend TypeScript contract types.

## Activity Fixtures

When the durable activity contract changes:

1. Update `workflow-activity-v1.schema.json` and `docs/contracts/workflow-activity-v1.md` together.
2. Update the `activity_contracts` entry in `fixtures/manifest.json`.
3. Add or update scenarios in `fixtures/workflow-activity-v1.json` for backend and frontend behavior.
4. Keep activity fixtures independent from raw LangGraph namespaces and arbitrary state dictionaries.

This is a pre-release zero-compatibility cutover. Replaced event fixtures and payload shapes are removed in the same change.
