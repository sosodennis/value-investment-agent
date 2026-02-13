# Deep Refactor Progress Tracker (Summary)
Date: 2026-02-13
Status: Historical summary (non-normative)
Plan Reference: `docs/deep-refactor-master-plan-2026-02-13.md`

This is the concise summary.
Full execution log is archived at:
- `docs/archive/deep-refactor-progress-2026-02-13.full.md`

## 1. Wave Status Snapshot

1. Wave 0 Guardrails: COMPLETED
2. Wave 1 Package Skeleton + Shared Base: COMPLETED
3. Wave 2 Contract Ownership Split: COMPLETED
4. Wave 3 Port Ownership Split: COMPLETED
5. Wave 4 Application Extraction from Nodes: COMPLETED
6. Wave 5 Mapper Split (Derive vs Format): COMPLETED
7. Wave 6 Cutover + Removal: COMPLETED
8. Wave 7 Hardening + Audit Pack: PARTIALLY COMPLETED (follow-up continued in later commits)

## 2. High-Impact Outcomes

1. Cross-agent global contract file removed and split to per-agent interface contracts.
2. Cross-agent global domain artifact ports removed and split to per-agent data ports with shared typed base.
3. Workflow node logic reduced to thinner orchestration paths; parsing/mapping moved to agent/application/interface layers.
4. Parser-first and zero-compat policy enforced with tests and boundary checks.
5. Naming convergence applied for major active agents (`application/use_cases.py`, `interface/contracts.py`).
6. Debate internals fully cut over to `src/agents/debate/**` (workflow-local `tools/` and `structures.py` removed).
7. Debate fact extraction rules moved from application to `domain/fact_builders.py`; application now orchestrates only data access + composition.
8. Debate state access helpers extracted to `application/state_readers.py`; `use_cases.py` further reduced to orchestration flow.
9. Debate logging and LLM message assembly extracted to `application/prompt_runtime.py`; `use_cases.py` now delegates prompt/runtime composition.
10. Debate cross-agent report aggregation extracted to `data/report_reader.py`; `use_cases.py` no longer performs direct fundamental/news/technical port reads.
11. Debate state shape extraction centralized in `application/debate_context.py`; `use_cases.py` no longer reads raw state via `state.get(...)`.
12. Debate report compression moved to `application/prompt_runtime.py`; `use_cases.py` keeps orchestration and delegates prompt/runtime mechanics.

## 3. Evidence and Verification Pattern

Typical verification executed during waves:
1. `ruff` checks on touched files.
2. Targeted agent tests.
3. Core regression suite:
   - `tests/test_protocol.py`
   - `tests/test_mappers.py`
   - `tests/test_news_mapper.py`
   - `tests/test_debate_mapper.py`
4. Architecture boundary check script:
   - `scripts/check_architecture_boundaries.py`

## 4. Interpretation Rule

1. This summary is historical and should not override canonical active guidelines.
2. For current rules, use:
   - `docs/README.md`
   - `docs/clean-architecture-engineering-guideline.md`
   - `docs/backend-guideline.md`
   - `docs/frontend-guideline.md`
