# Agent Skill Update Plan (Vertical Slice Refactor Lessons)

## Purpose
Summarize the cross-agent, vertical-slice refactor experience and specify what will be updated in each skill template.
This plan is intentionally generic (not fundamental-specific) so it can guide future agent refactors and new agent design.

## Scope
Skills to update:
- `agent-refactor-executor`
- `architecture-modification-planner`
- `architecture-standard-enforcer`
- `agent-debug-review-playbook`

## Cross-Cutting Lessons to Encode
1. **Vertical slice boundaries must be explicit and enforceable.**
   - Each subdomain owns its contracts, policies, and adapters.
   - Shared kernel exists only for truly cross-subdomain contracts (e.g., traceable/provenance).
2. **Decide contract ownership by boundary, not by convenience.**
   - Domain: deterministic business concepts and policies.
   - Application: use-case ports and orchestration APIs.
   - Interface: boundary DTOs/serializers/projections.
   - Infrastructure: adapters and provider wiring only.
3. **No compatibility shims in clean-cut migrations.**
   - Migrate call sites atomically within a slice.
   - Remove old paths in the same slice after validation.
4. **Pipeline-heavy infra should be grouped by stage.**
   - Use stage subpackages (e.g., `fetch/`, `extract/`, `map/`, `filtering/`, `matching/`, `postprocess/`) to reduce fragmentation.
5. **Naming hygiene is non-negotiable.**
   - No `*utils*`, `*helpers*`, or generic catch-all in mature paths.
   - Owner name must match role and file name (service/policy/provider/mapper/etc).
6. **Validation gates are per-slice and must be targeted.**
   - Each slice has a minimal test set that proves the move.
   - Lint + import hygiene + architecture compliance after each slice.
7. **Empty layer directories are treated as debt.**
   - Remove empty layer packages and directories after migration.
8. **Risk classification is structural, not LOC-based.**
   - Cross-layer rewiring, contract moves, async boundary changes are small but high-risk.
9. **Decision trace must be explicit.**
   - When moving a contract or splitting a module, record the decision rationale and the rule used.

## Planned Updates by Skill

### 1) `agent-refactor-executor`
**Add/strengthen:**
- **Decision checkpoint per slice**: explicitly document the rule used for ownership moves (domain vs interface vs application).
- **No-compat rule**: “compat shims/re-exports are prohibited unless explicitly approved.”
- **Empty layer cleanup step**: remove empty directories as part of slice completion.
- **Old-path sweep step**: run `rg` on legacy imports before closing each slice.
- **Pipeline refactor guideline**: re-package large infra by stage before micro-splitting files.
- **Risk trigger list expansion**: add “contract relocation” and “import graph rewiring” as high-risk, requiring `small` slices.
- **Validation gate template**: include `architecture-standard-enforcer` as default gates.

### 2) `architecture-modification-planner`
**Add/strengthen:**
- **Boundary decision rubric**: a small decision table for contract placement:
  - Domain if business concept/policy (deterministic).
  - Interface if external boundary or projection/serialization.
  - Application if use-case port or orchestration boundary.
- **Subdomain split criteria**:
  - Stable capability boundary, unique dependencies, or high coupling within a capability.
  - Pipeline or multi-stage processing tends to be a subdomain candidate.
- **Migration plan template**:
  - Explicit “old → new mapping” table.
  - Step that lists “legacy removal” items per slice.
- **Validation plan checklist**:
  - Lint, target tests, import hygiene, and performance gates (if heavy compute).
- **Decision log section**:
  - Record why a module moves or why a split is chosen.

### 3) `architecture-standard-enforcer`
**Add/strengthen:**
- **Explicit check for empty layer packages**: flag empty `application/`, `domain/`, `interface/`, `infrastructure`.
- **Legacy import scan**: verify no old-path imports remain after migration.
- **Pipeline packaging check**: if infra is large and pipeline-based, ensure stage subpackages exist.
- **Contract ownership validation**: ensure preview/projection contracts are in interface, not domain.
- **No generic modules**: enforce removal or renaming of `*utils*`, `*common*`, `*helpers*`.

### 4) `agent-debug-review-playbook`
**Add/strengthen:**
- **Import cycle triage**: steps to detect and isolate circular imports introduced by refactors.
- **Boundary-violation audit**: quickly check interface → domain or application → infrastructure leaks.
- **Legacy residue check**: verify old-path imports and empty directories are not left behind.
- **Contract mismatch checks**:
  - verify serialization/projection functions align with new contract owners.
- **Minimal remediation rules**:
  - fix by moving the smallest unit (function/contract) rather than broad rewrites.

## Deliverables
1. Update each skill template with the items above.
2. Keep updates generic and reusable across all agents.
3. Ensure new rules do not conflict with existing standards.

## Non-Goals
- No code changes to agents in this step.
- No fundamental-specific rules or file names.
