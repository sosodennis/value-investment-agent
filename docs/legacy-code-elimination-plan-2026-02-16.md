# Legacy Code Elimination Plan (Zero-Compatibility)
Date: 2026-02-16
Scope: `finance-agent-core`
Policy: No compatibility branches, no dual paths, fail-fast.

## 1. Objective
Remove legacy and redundant code package-by-package to maximize maintainability and reduce cognitive load before production launch.

Success criteria:
1. No dead modules in runtime path.
2. No duplicate responsibility across layers/packages.
3. No legacy compatibility code.
4. Every remaining module has a clear layer responsibility and at least one verified consumer.

## 2. What Counts as Legacy
Code is considered legacy if any of these is true:
1. No runtime or test consumer.
2. Duplicates behavior now provided by canonical contracts/ports/parsers.
3. Violates current layer ownership (`domain/application/data/interface`).
4. Exists only for migration/compatibility.
5. Old package path still present after namespace move.

## 3. Audit Method (Per Package)
For each package, run this flow:
1. Build static reference map (imports + symbol usage).
2. Validate runtime reachability via targeted tests.
3. Classify each module: `KEEP`, `MOVE`, `MERGE`, `DELETE`.
4. Remove dead code atomically (no fallback).
5. Re-run quality gates.

Evidence required before deletion:
1. No valid consumer in `src/`, `api/`, `tests/`.
2. No required path from workflow entrypoints.
3. Tests pass after removal.

## 4. Package-by-Package Analysis Plan
## Wave A: Foundation (highest ROI)
1. `src/infrastructure`
2. `src/services`
3. `src/interface/artifacts`
4. `src/interface/events`
5. `src/shared/kernel`
6. `src/shared/cross_agent`
7. Residual legacy namespaces (`src/common`, `src/shared/application`, `src/shared/data`, `src/shared/domain`, `src/shared/interface`)

Focus checks:
1. Utilities with zero consumers.
2. Old wrappers replaced by typed ports/contract registry.
3. Namespace leftovers from recent refactor.

## Wave B: Workflow Shell
1. `src/workflow`
2. `src/workflow/nodes/*`

Focus checks:
1. Thin wrappers vs actual orchestration value.
2. Any duplicate DTO/schema/state definitions that belong in agent packages.
3. Old subgraph scaffolding no longer used by `src/agents/*`.

## Wave C: Agent Packages
Analyze each agent with the same checklist:
1. `src/agents/intent`
2. `src/agents/fundamental`
3. `src/agents/news`
4. `src/agents/technical`
5. `src/agents/debate`

Per-layer checklist:
1. `domain`: business rules only, no I/O, no API DTO.
2. `application`: orchestration/use-cases only, no provider SDK.
3. `data`: external I/O + repository/ports implementation only.
4. `interface`: contract/parsers/serializers only, no business decisions.

## 5. Immediate High-Priority Candidates (from current baseline)
1. `finance-agent-core/src/infrastructure/serialization.py`
   - Current status: no references in `src/`, `api/`, `tests`.
   - Planned action: verify once in Wave A, then delete if still unreferenced.
2. Old namespace residues (`src/common/**`, `src/shared/(application|data|domain|interface)/**`)
   - Current status: only `__pycache__` artifacts.
   - Planned action: remove directories from repo tree and enforce path policy.

## 6. Required Gates Per Slice
After every deletion/move slice:
1. `uv run --project finance-agent-core python -m ruff check <touched-files>`
2. `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_protocol.py finance-agent-core/tests/test_mappers.py finance-agent-core/tests/test_news_mapper.py finance-agent-core/tests/test_debate_mapper.py -q`
3. Contract suites when artifact/interface touched:
   - `finance-agent-core/tests/test_artifact_contract_registry.py`
   - `finance-agent-core/tests/test_artifact_api_contract.py`
   - `finance-agent-core/tests/test_output_contract_serializers.py`
   - `finance-agent-core/tests/test_protocol_fixtures.py`

## 7. Operating Rules (No Tech Debt)
1. No TODO fallback branches.
2. No “temporary” parallel paths.
3. Delete or move in the same slice as call-site updates.
4. If responsibility is unclear, classify first in docs, then refactor.

## 8. Tracking
Use this register as execution log:
1. `docs/legacy-code-audit-register-2026-02-16.md`

Each row must include:
1. package/module
2. issue type
3. evidence
4. action (`KEEP/MOVE/MERGE/DELETE`)
5. test evidence
6. status
