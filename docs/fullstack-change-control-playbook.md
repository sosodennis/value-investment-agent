# Fullstack Change Control Playbook (Audit-Ready)
Date: 2026-02-12
Applies to: `/finance-agent-core` + `/frontend` monorepo

## 1. Objective

Prevent maintainability and sustainability degradation by enforcing a traceable, testable, and reviewable process for cross-stack changes.

This playbook defines:

1. Mandatory control points
2. End-to-end change workflow
3. Required evidence for external audit
4. Standard use-case procedures with pseudo code

## 2. Control Objectives

Every cross-stack change must guarantee:

1. Contract integrity: backend and frontend remain synchronized.
2. Deterministic validation: failures are blocked in CI, not discovered in production.
3. Zero-compat governance: breaking changes are merged as one atomic backend+frontend change set.
4. Traceability: audit can map requirement -> code -> tests -> release decision.

## 3. Roles (RACI Style)

1. Backend Owner:
   - Owns API/SSE schema and protocol evolution.
2. Frontend Owner:
   - Owns rendering, parser compatibility, UX behavior.
3. Contract Owner:
   - Owns `contracts/` assets and fixture policy.
4. Reviewer (cross-functional):
   - Backend changes require frontend reviewer.
   - Frontend protocol changes require backend reviewer.

## 4. Authoritative Sources of Truth

1. REST contract source:
   - FastAPI response models in backend
   - Generated OpenAPI: `contracts/openapi.json`
2. Frontend type source:
   - Generated from OpenAPI:
     `frontend/src/types/generated/api-contract.ts`
3. SSE behavior source:
   - Backend protocol model: `finance-agent-core/src/interface/protocol.py`
   - Shared fixtures: `contracts/fixtures/*.json`
   - Fixture manifest: `contracts/fixtures/manifest.json`

## 5. Mandatory Pipelines

1. Contract generation:
```bash
bash scripts/generate-contracts.sh
```

2. Fixture validation:
```bash
python3 scripts/validate-sse-fixtures.py
```

3. Backend checks:
```bash
cd finance-agent-core
UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check src api tests
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_protocol.py tests/test_protocol_fixtures.py -q
```

4. Frontend checks:
```bash
cd frontend
npm run lint
npm run typecheck
npm run test -- --run
```

## 6. Standard Workflow (All Use Cases)

1. Create/change issue and classify:
   - additive / non-breaking / breaking
2. Define the single PR blast radius before coding:
   - backend schema + contract artifacts + frontend parser + frontend rendering + tests
3. Update contract first (or in same commit set):
   - backend schema + contract artifacts + fixtures
4. Implement backend behavior.
5. Implement frontend consumption/rendering with parser-first boundaries:
   - runtime decode in protocol/parser layer
   - domain parser module per agent output
   - UI consumes parsed view model only
6. Update tests:
   - backend protocol/mappers
   - frontend protocol/rendering
   - shared fixture validation
7. Run local gates.
8. Submit PR with template checklist.
9. Merge only after CI and cross-functional review pass.

## 7. Required Audit Evidence Per PR

1. PR link and merged commit hash
2. Contract artifact diff (`contracts/openapi.json`, fixtures)
3. Test evidence (backend/frontend/fixture)
4. Breaking impact statement (if breaking)
5. Rollback plan

---

## 8. Use Case A: Add a New Agent (Backend)

### Goal

Add a new sub-agent into workflow and expose outputs safely to frontend.

### Procedure

1. Define backend state context (`TypedDict`) and node status keys.
2. Emit canonical artifact payload (`summary/preview/reference`).
3. Ensure adapter and mapper can surface output as `state.update`.
4. Generate OpenAPI and sync frontend types.
5. Register frontend UI renderer and status card.
6. Add protocol and rendering tests.

### Pseudo (Backend)

```python
# workflow/state.py
class NewAgentContext(TypedDict):
    status: NotRequired[str | None]
    artifact: NotRequired[AgentOutputArtifactPayload | None]

class AgentState(TypedDict):
    new_agent: Annotated[NewAgentContext, merge_dict]

# workflow/nodes/new_agent/nodes.py
def new_agent_node(state: AgentState) -> Command:
    preview = {"status_label": "ready", "metric": "42"}
    artifact = build_artifact_payload(
        summary="New agent completed",
        preview=preview,
        reference=None,
    )
    return Command(
        update={
            "new_agent": {"status": "done", "artifact": artifact},
            "node_statuses": {"new_agent": "done"},
        }
    )
```

### Pseudo (Frontend)

```ts
// config/agents.ts
{
  id: "new_agent",
  name: "New Agent",
  ...
}

// AgentOutputTab switch
if (agent.id === "new_agent") {
  return <NewAgentOutput output={rawOutput} status={status} />;
}
```

### Controls

1. No `Any`, no duck typing fallback.
2. Must use canonical artifact payload.
3. Must include fixture and parser validation if event shape changes.

---

## 9. Use Case B: Display a New Output in Frontend

### Goal

Render a new preview/reference output without breaking existing agents.

### Procedure

1. Add/adjust backend preview fields (small, stable, serializable).
2. If API schema changed, regenerate contracts.
3. Create or update a dedicated preview parser module:
   - `frontend/src/types/agents/<domain>-preview-parser.ts`
4. Extend output component to consume parsed preview model only.
5. Add parser test + UI/contract test coverage.

### Pseudo

```python
# backend mapper
preview = {
  "score_display": "87",
  "label": "high confidence",
}
artifact = build_artifact_payload(summary="Analysis done", preview=preview, reference=ref)
```

```ts
// frontend parser module
export const parseNewDomainPreview = (value: unknown): NewDomainPreview | null => {
  // strict runtime validation, throw on invalid field types
};

// frontend output component
const preview = parseNewDomainPreview(output?.preview, "new_domain.preview");
const score = preview?.score_display ?? "N/A";
```

### Controls

1. New output fields must be optional-safe in frontend.
2. No direct assumptions on nullable fields.
3. Parser and UI must be split by responsibility:
   - parser file validates shape
   - component file renders parsed data
4. Contract artifacts must be regenerated when schema changes.

---

## 10. Use Case C: Remove Class or Output (Backend + Frontend)

### Goal

Remove class/field/output under zero-compat policy without leaving hidden consumer drift.

### Procedure

1. Mark target as `BREAKING` in PR title/description.
2. Remove old backend field/class/output and update contract artifacts in the same PR.
3. Update frontend parser/component to new shape in the same PR.
4. Update fixtures and tests to the new canonical shape only.
5. Fail PR if any old field/class/output remains in parser/tests.

### Pseudo

```python
# single-phase breaking removal
def build_output() -> dict[str, object]:
    return {"new_field": new_value}
```

```ts
// parser rejects stale field and accepts only new contract shape
const parsed = parseNewContract(payload);
const val = parsed.new_field;
```

### Exit Criteria for Deletion

1. No active consumer depends on old class/output.
2. Fixture manifest and tests no longer include old version/field.
3. Removal documented in changelog/PR.

---

## 11. Additional Use Cases To Cover (Recommended)

For external audit completeness, also cover:

1. Rename existing field (breaking, single PR atomic cutover)
2. Add a new interrupt type (schema + UI form + resume payload)
3. SSE protocol version bump (`v1` -> `v2`)
4. Emergency rollback of protocol change
5. Contract-only refactor (no behavior change)
6. Removing an agent entirely from workflow
7. Artifact reference format change (`download_url`, `type`, id rules)

---

## 12. Zero-Compatibility Protocol Policy

Current policy:

1. `supported_versions` in manifest are production-compatible.
2. New protocol version adoption is atomic:
   - backend emit + frontend parser + fixtures + tests ship in same PR
3. No long-lived dual support window in runtime code.
4. Old protocol fixtures are removed from `supported_versions` in the same breaking PR.

See:

1. `docs/sse-protocol-migration-checklist.md`
2. `docs/sse-v2-migration-pr-example.md`

---

## 13. Anti-Patterns (Audit Red Flags)

1. Backend contract changed but no regenerated artifacts committed.
2. Frontend parser accepts unknown protocol versions silently.
3. Deleting fields/classes without same-PR frontend parser update.
4. Reintroducing `enumNames`, `Any`, or duck-typing fallbacks in core flows.
5. Skipping fixture validation for protocol changes.
6. Reintroducing runtime type assertions (`as`) in frontend runtime paths.

---

## 14. Definition of Sustainable Change

A change is considered sustainable only if:

1. Contract is explicit and machine-validated.
2. Behavior is covered by backend and frontend tests.
3. Breaking scope and rollback are documented.
4. CI gates enforce the policy without human memory dependency.
