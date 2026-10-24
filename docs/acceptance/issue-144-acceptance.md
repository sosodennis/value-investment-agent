# Issue 144 acceptance evidence

Status: `VERIFIED` for the documentation-only baseline gate.

## Scope and result

Issue #144 freezes the full-stack ownership map and cutover contracts. The
artifacts are:

- `docs/refactor-map/ownership-and-contract-inventory.md`
- `docs/refactor-map/deletion-ledger.md`
- `docs/refactor-map/README.md`

Only `docs/` files changed for this issue. No backend, frontend, standalone
service, migration, fixture, or dependency source was edited.

Base SHA: `1f9d0745fa0625684c98506c89d750cb8c98161b`

## Grounding evidence

The inventory was derived from the baseline source and the canonical guides:

- `finance-agent-core/api/server.py` routes, run state, projection, replay, and
  SSE generator.
- `finance-agent-core/src/infrastructure/models.py` persistence models.
- `finance-agent-core/src/workflow/state.py` and each agent workflow state for
  `internal_progress`, `node_statuses`, and `current_node`.
- `finance-agent-core/src/agents/*/entrypoint.py` public graph entrypoints.
- `finance-agent-core/src/interface/events/` event protocol and adapter.
- `finance-agent-core/src/llm_provider/`, `src/model_inference/`,
  `src/search/`, and `src/search_settings/` typed service boundaries.
- `frontend/src/app`, `src/hooks`, `src/lib`, `src/types`, and `src/components`
  feature consumers and parsers.
- `contracts/openapi.json` and `contracts/fixtures/sse-events-v1.json` current
  generated contract and fixture baseline.

## Commands and results

Run from the repository root at the base commit before the documentation edit:

```text
python3 scripts/architecture_guard.py
Architecture guard passed with no boundary violations.
```

Route and legacy state inventory:

```text
rg -n '(@router|@app)\.(get|post|put|patch|delete)|APIRouter\(' \
  finance-agent-core/api finance-agent-core/src
rg -n 'internal_progress|node_statuses|current_node|astream_events|text/event-stream' \
  finance-agent-core/src finance-agent-core/api frontend/src contracts
```

These searches produced the current paths recorded in the inventory and
deletion ledger. The baseline has legacy activity state and unversioned routes
by design; they are documented as implementation work for #145/#146 rather
than changed in #144.

Diff boundary check after the edit:

```text
git diff --name-only 1f9d0745fa0625684c98506c89d750cb8c98161b
docs/acceptance/issue-144-acceptance.md
docs/refactor-map/README.md
docs/refactor-map/deletion-ledger.md
docs/refactor-map/ownership-and-contract-inventory.md
```

## Verdict

`VERIFIED`: the ownership map, canonical names, route/event contract handoff,
fresh database baseline, and explicit deletion actions are present; the
architecture guard passes at baseline; and the diff is documentation-only.

The live backend/frontend behavior remains `NOT VERIFIED` by this issue. That
is intentional and belongs to #148, #145, #146, and #147. No Docker or live
provider behavior was required or changed for this documentation gate.

## Open handoff gaps

- #148 must publish the typed `workflow.activity` contract and shared fixtures
  before backend/frontend implementation starts.
- #145 must turn the target route names into Pydantic/OpenAPI schemas, rebuild
  the fresh database, remove `internal_progress`, and regenerate architecture
  actions after source migration.
- #146 must consume generated OpenAPI and #148 fixtures through feature-owned
  parsers and reducers.
- #147 must prove multi-worker delivery and run the final stale-path sweep.
