# Full-Stack Refactor Baseline

Date: 2026-10-24
Canonical instruction: `.audit/architect-full-stack-refactor-instruction-2026-10-24.md`

## Repository

- Baseline branch: `main`
- Baseline SHA: `1f9d0745fa0625684c98506c89d750cb8c98161b`
- Tracked worktree: clean at baseline; existing untracked audit/research files are preserved and are not part of the refactor.
- Architecture guard: `python3 scripts/architecture_guard.py` -> `Architecture guard passed with no boundary violations.`

## Baseline checks

- Backend: `LLM_PROVIDER_SERVICE_URL=http://127.0.0.1:8002 LLM_PROVIDER_SERVICE_TOKEN=baseline MODEL_INFERENCE_SERVICE_URL=http://127.0.0.1:8001 MODEL_INFERENCE_TOKEN=baseline SEARCH_SERVICE_URL=http://127.0.0.1:8003 SEARCH_SERVICE_TOKEN=baseline FRED_API_KEY=baseline UV_CACHE_DIR=/tmp/via-uv-cache uv run pytest -q` -> `974 passed, 5 skipped`.
- Frontend lint: `npm run lint` -> pass.
- Frontend typecheck: `npm run typecheck` -> pass.
- Frontend tests: `npm run test -- --run` -> `117 passed` across 20 files.
- First backend probe without service URL variables failed during collection with the explicit configuration error `LLM_PROVIDER_SERVICE_URL is required`; the environment-complete rerun above is the accepted baseline.

## Worktrees and Compose assignments

All worktrees were created from the baseline SHA before implementation:

| Owner | Branch | Worktree | Compose project | Backend port | Frontend port |
| --- | --- | --- | --- | ---: | ---: |
| Engineer A | `codex/refactor-contract-a` | `/Users/denniswong/.codex/worktrees/refactor-contract-a/value-investment-agent` | `via-refactor-contract-a` | 8200 | 3200 |
| Engineer B | `codex/refactor-backend-b` | `/Users/denniswong/.codex/worktrees/refactor-backend-b/value-investment-agent` | `via-refactor-backend-b` | 8300 | 3300 |
| Engineer C | `codex/refactor-frontend-c` | `/Users/denniswong/.codex/worktrees/refactor-frontend-c/value-investment-agent` | `via-refactor-frontend-c` | 8400 | 3400 |
| Integration | `codex/refactor-integration` | `/Users/denniswong/.codex/worktrees/refactor-integration/value-investment-agent` | `via-refactor-integration` | 8500 | 3500 |

Each project must use project-scoped volumes/networks, explicit host-port overrides, and no fixed `container_name`. `BACKEND_HOST_PORT` is the source for any local staging backend origin; `STAGING_BASE_URL` is not required.

## Existing Docker state

- `via-llm-stage`: backend `127.0.0.1:8100` healthy, PostgreSQL `5433` healthy, Redis `6380` healthy, LLM gateway `4001` healthy, frontend `3100` running.
- `via-llm-provider`: backend `127.0.0.1:8000` healthy, PostgreSQL `5432` healthy, Redis `6379` healthy, frontend `3000` running; gateway was starting when inspected.
- Root Compose config requires `LITELLM_MASTER_KEY` only when the `llm-gateway` profile is selected. No secret value is recorded here.

## Known stale paths at baseline

- `internal_progress` remains in root and agent states, application updates, incident logging, and tests.
- Migration-era `subdomains/` and root workflow paths remain in the backend.
- `api/server.py` still combines composition, graph/run lifecycle, persistence/projection, replay, and SSE concerns.
- Frontend has multiple activity/progress parsers and global workflow consumers that are in scope for #146.
