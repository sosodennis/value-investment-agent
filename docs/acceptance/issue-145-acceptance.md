# Issue 145 acceptance evidence

Status: `VERIFIED` for the backend architecture and runtime gate.

## Result

Backend commit `5fd7ac958246ed05971c969d0e1412a56babe5fa` was merged into the
integration cutover at `e2fdf73`. The change reduces `api/server.py` to
composition, moves workflow execution and durable activity transport behind
`analysis_runtime`, enforces ownership before replay/subscription, and removes
the legacy event adapters, workspace projection package, obsolete ORM tables,
and their tests.

## Independent checks

Run from the integration worktree:

```text
LLM_PROVIDER_SERVICE_URL=http://127.0.0.1:8002 \
LLM_PROVIDER_SERVICE_TOKEN=baseline \
MODEL_INFERENCE_SERVICE_URL=http://127.0.0.1:8001 \
MODEL_INFERENCE_TOKEN=baseline \
SEARCH_SERVICE_URL=http://127.0.0.1:8003 \
SEARCH_SERVICE_TOKEN=baseline \
FRED_API_KEY=baseline uv run pytest -q
934 passed, 5 skipped

uv run ruff check src tests
All checks passed

python -m compileall -q api src tests
python3 scripts/architecture_guard.py
Architecture guard passed with no boundary violations.
```

The final source sweep found no `internal_progress`, `src.interface.events`,
`workspace_runtime_projection`, `WorkspaceRuntime`, or legacy `AgentEvent`
references in backend source or tests.

## Docker and behavior

The isolated Compose project is `via-refactor-integration`. Fresh PostgreSQL
contains `workflow_activity_events`, `workflow_activity_cursors`, and
`workflow_runs`; no `workspace_runtime_*` tables exist. Backend workers on
ports 8200 and 8201, PostgreSQL, Redis, LLM Provider, and Search all reported
healthy. A local authenticated run returned `202`; the second worker received
17 `workflow.activity` events and a terminal event, then returned snapshot
cursor 17. After stopping and restarting worker 2, replay returned the same
17 events and terminal event from durable storage.

## Verdict

`VERIFIED`. The backend diff, full tests, architecture checks, fresh schema,
Docker health, ownership, live fan-out, replay, and worker restart behavior
were independently inspected.
