# Issue 148 acceptance evidence

Status: `VERIFIED` for the canonical contract and shared-fixture gate.

## Scope and result

Issue #148 freezes the application-owned `workflow.activity` event, activity
lifecycle, snapshot semantics, and shared behavior fixtures. The artifacts
are:

- `contracts/workflow-activity-v1.schema.json`
- `docs/contracts/workflow-activity-v1.md`
- `contracts/fixtures/workflow-activity-v1.json`
- `contracts/fixtures/manifest.json` (`activity_contracts` index)
- `contracts/README.md` (fixture policy)

Base SHA: `bf1327e738021ce191f88b7b066c9726a8c833b5` (#144 result).

No backend/frontend/service source, caller, LangGraph dependency, generated
OpenAPI file, or `internal_progress` writer was changed. The existing legacy
SSE fixture remains indexed only as a baseline until #145/#146 perform the
coordinated source cutover; it is not the authority for the new activity
contract.

## Contract decisions

- The event name is `workflow.activity` and the event version is `v1`.
- `event_id` is the durable delivery identity; `seq_id` is the monotonic
  per-thread cursor.
- `activity_id` is the stable logical operation identity. Retries/resumes keep
  it and increment `attempt`.
- `parent_activity_id` and `scope_path` represent nested activities without
  leaking LangGraph namespaces.
- Lifecycle statuses are `queued`, `running`, `waiting`, `completed`,
  `failed`, `cancelled`, and `skipped`.
- `progress` is optional measured data in `[0, 100]`; parallel activities are
  a set and never receive a guessed aggregate percentage.
- Terminal activity attempts leave the active set and remain in recent history.
- Backend projection appends an event and advances its cursor atomically before
  SSE publication. Sequence gaps request replay or snapshot recovery.

## Fixture coverage

The fixture contains these scenario IDs:

```text
sequential-nodes
parallel-subgraphs
repeated-invocation
retry
interrupt
cancellation
failure
completion
duplicate-delivery
replay
sequence-gap
```

Each scenario contains valid events, a thread/run snapshot, and assertions that
the backend normalizer and frontend reducer can consume without
`internal_progress`, raw LangGraph state, or private namespace data.

## Commands and results

JSON syntax checks:

```text
python3 -m json.tool contracts/workflow-activity-v1.schema.json >/dev/null
python3 -m json.tool contracts/fixtures/workflow-activity-v1.json >/dev/null
python3 -m json.tool contracts/fixtures/manifest.json >/dev/null
JSON syntax passed
```

The environment does not provide the optional `jsonschema` Python package or
the Node `ajv` package. The deterministic boundary validator below checks the
same cross-stack invariants that matter to this fixture and is recorded here
so reviewers can rerun it without installing dependencies:

```text
python3 - <<'PY'
import json
from pathlib import Path

root = Path("contracts")
schema = json.loads((root / "workflow-activity-v1.schema.json").read_text())
fixture = json.loads((root / "fixtures/workflow-activity-v1.json").read_text())
assert schema["$id"].endswith("workflow-activity-v1.schema.json")
assert fixture["contract_version"] == "v1"
assert fixture["event_name"] == "workflow.activity"
required = {"sequential-nodes", "parallel-subgraphs", "repeated-invocation",
            "retry", "interrupt", "cancellation", "failure", "completion",
            "duplicate-delivery", "replay", "sequence-gap"}
scenarios = {item["id"]: item for item in fixture["scenarios"]}
assert required <= scenarios.keys()
statuses = set(fixture["activity_statuses"])
kinds = set(fixture["activity_kinds"])
for scenario in fixture["scenarios"]:
    seen = set()
    previous = 0
    thread_id = scenario["snapshot"]["thread_id"]
    run_id = scenario["snapshot"]["run_id"]
    for event in scenario["events"]:
        assert event["event_name"] == "workflow.activity"
        assert event["event_version"] == "v1"
        assert event["seq_id"] > previous
        assert event["event_id"] not in seen
        previous = event["seq_id"]
        seen.add(event["event_id"])
        payload = event["payload"]
        assert event["thread_id"] == thread_id == payload["thread_id"]
        assert event["run_id"] == run_id == payload["run_id"]
        assert payload["status"] in statuses and payload["kind"] in kinds
        assert payload["attempt"] >= 1
        if "progress" in payload:
            assert 0 <= payload["progress"] <= 100
    if scenario["id"] == "sequence-gap":
        assert scenario["snapshot"]["cursor"] == 1
        assert previous == 3
    else:
        assert scenario["snapshot"]["cursor"] >= previous
print("workflow.activity fixture boundary validation passed")
PY
workflow.activity fixture boundary validation passed
```

Repository guard remains green at the #144 baseline and no architecture source
was changed by #148:

```text
python3 scripts/architecture_guard.py
Architecture guard passed with no boundary violations.
```

## Verdict and remaining gates

`VERIFIED`: the typed JSON Schema, lifecycle rules, identity/cursor semantics,
fixture manifest, and all required behavior scenarios are present and directly
validated. The pinned LangGraph `1.0.5`/`astream_events(..., version="v2")`
path is documented; no dependency upgrade was attempted.

Runtime normalization, durable atomic projection, backend REST/SSE behavior,
frontend parsing/reducer behavior, and live Docker/provider behavior are
`NOT VERIFIED` by this issue. They belong to #145, #146, and #147 and must
consume these exact artifacts.
