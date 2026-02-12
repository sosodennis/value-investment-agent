# Contracts

This folder contains generated cross-stack contracts used by both backend and frontend.

## Files

1. `openapi.json`: Exported from FastAPI (`finance-agent-core/api/server.py`).

## Generate

From repository root:

```bash
bash scripts/generate-contracts.sh
```

This command will:

1. Export backend OpenAPI to `contracts/openapi.json`.
2. Generate frontend TypeScript contract types at:
   `frontend/src/types/generated/api-contract.ts` using `openapi-typescript`.
