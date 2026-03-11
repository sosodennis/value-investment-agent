# Intent Agent Vertical Slice Refactor Plan

## Requirement Breakdown
- Align `src/agents/intent` with the same clean-cut vertical slice standards used in fundamental.
- Remove legacy/empty packages and generic catch-all module names.
- Clarify boundary ownership for contracts, policies, and adapters.
- Reduce domain fragmentation and improve naming cohesion.
- Preserve runtime behavior and workflow contracts.

## Technical Objectives and Strategy
- Keep `domain/` for deterministic policies and value objects only.
- Keep `application/` for orchestration and runtime port usage (LLM + providers).
- Keep `interface/` for DTOs, parsers, serializers, prompt specs/renderers, and preview projections.
- Keep `infrastructure/` for provider adapters only.
- Remove empty `data/` package and any unused stubs.
- Rename generic modules to explicit, role-matching owners.
- Avoid compatibility shims; migrate call sites atomically per slice.

## Involved Files
- `finance-agent-core/src/agents/intent/domain/models.py`
- `finance-agent-core/src/agents/intent/domain/policies.py`
- `finance-agent-core/src/agents/intent/domain/extraction_policies.py`
- `finance-agent-core/src/agents/intent/application/intent_service.py`
- `finance-agent-core/src/agents/intent/application/orchestrator.py`
- `finance-agent-core/src/agents/intent/interface/mappers.py`
- `finance-agent-core/src/agents/intent/interface/serializers.py`
- `finance-agent-core/src/agents/intent/interface/parsers.py`
- `finance-agent-core/src/agents/intent/interface/contracts.py`
- `finance-agent-core/src/agents/intent/interface/prompt_specs.py`
- `finance-agent-core/src/agents/intent/interface/prompt_renderers.py`
- `finance-agent-core/src/agents/intent/infrastructure/market_data/*`
- `finance-agent-core/src/agents/intent/infrastructure/search/*`
- `finance-agent-core/src/agents/intent/data/*` (empty)
- Tests: `tests/test_intent_mapper.py`, `tests/test_intent_application_use_cases.py`, `tests/test_error_handling_intent.py`, `tests/test_interrupts.py`, `tests/test_intent_interface_parsers.py`, `tests/test_intent_company_profile_provider.py`

## Detailed Per-File Plan

### Slice 1 (small): Remove Empty/Legacy and Rename Generic Domain Owners
Objective:
- Remove empty `data/` package.
- Rename generic domain owners to explicit roles.

Changes:
- `domain/models.py` → `domain/ticker_candidate.py`
- `domain/policies.py` → `domain/clarification_policy.py`
- `domain/extraction_policies.py` → `domain/heuristic_intent_policy.py`
- Update all imports in application/interface/tests.

Entry/Exit:
- Entry: no external dependencies on `data/` package.
- Exit: no `models.py`/`policies.py`/`extraction_policies.py` remain; all imports updated.

Validation:
- `ruff check finance-agent-core/src/agents/intent`
- `pytest tests/test_intent_mapper.py tests/test_intent_application_use_cases.py tests/test_error_handling_intent.py -q`

### Slice 2 (small): Interface Cohesion (Split Generic Mapper)
Objective:
- Replace `interface/mappers.py` with explicit projection/mapper owners.

Changes:
- `interface/mappers.py` → split into:
  - `interface/intent_preview_projection_service.py` (summarize preview)
  - `interface/ticker_candidate_mapper.py` (to/from candidate models)
- Update `parsers.py`, `serializers.py`, `application/orchestrator.py`, and tests.

Entry/Exit:
- Entry: Slice 1 complete.
- Exit: no `mappers.py` remains; all references updated.

Validation:
- `pytest tests/test_intent_mapper.py tests/test_interrupts.py -q`

### Slice 3 (medium): Application Service Cohesion
Objective:
- Separate deterministic candidate policies from LLM-driven extraction.

Changes:
- `application/intent_service.py` → `application/intent_extraction_service.py`
  - keep LLM extraction paths here.
- Move `deduplicate_candidates` to `domain/candidate_deduplication_policy.py`
- Update `application/orchestrator.py` imports and call sites.
- Update tests importing `_heuristic_extract` or other helpers.

Entry/Exit:
- Entry: Slice 2 complete.
- Exit: no `intent_service.py` remains; deterministic candidate policy is in domain.

Validation:
- `pytest tests/test_intent_application_use_cases.py tests/test_error_handling_intent.py tests/test_agent_subgraph_entrypoints.py -q`

### Slice 4 (small): Migration Hygiene Sweep
Objective:
- Ensure no legacy paths or empty layers remain after renames.

Changes:
- Remove empty directories if any were created by moves.
- Run old-path search and confirm no legacy imports.

Validation:
- `rg "agents.intent.domain.models|agents.intent.domain.policies|agents.intent.domain.extraction_policies|interface.mappers|application.intent_service" finance-agent-core/src finance-agent-core/tests -g"*.py"`
- `find finance-agent-core/src/agents/intent -type d -empty`

## Old → New Mapping
- `domain/models.py` → `domain/ticker_candidate.py`
- `domain/policies.py` → `domain/clarification_policy.py`
- `domain/extraction_policies.py` → `domain/heuristic_intent_policy.py`
- `interface/mappers.py` → `interface/intent_preview_projection_service.py`
- `interface/mappers.py` → `interface/ticker_candidate_mapper.py`
- `application/intent_service.py` → `application/intent_extraction_service.py`
- `application/intent_service.deduplicate_candidates` → `domain/candidate_deduplication_policy.py`

## Risk/Dependency Assessment
- Moderate import churn risk due to file renames (domain/interface/application).
- Low runtime risk if contracts remain unchanged and call sites updated atomically.
- Potential circular-import risk if interface and domain imports are not kept one-way.

## Validation and Rollout Gates
- Lint: `ruff check finance-agent-core/src/agents/intent`
- Targeted tests:
  - `tests/test_intent_mapper.py`
  - `tests/test_intent_application_use_cases.py`
  - `tests/test_error_handling_intent.py`
  - `tests/test_interrupts.py`
  - `tests/test_intent_interface_parsers.py`
  - `tests/test_intent_company_profile_provider.py`
- Migration hygiene:
  - `rg` legacy path sweep
  - Empty directory check

## Assumptions/Open Questions
- No compatibility shims are allowed unless explicitly approved.
- Confirm no external (non-repo) consumers import old intent module paths.
- Confirm that moving `deduplicate_candidates` into domain is acceptable (pure deterministic logic).
