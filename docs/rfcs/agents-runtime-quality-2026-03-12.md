# RFC: Agents Runtime Quality Fixes (2026-03-12)

## Context
Post-refactor review found blocking sync I/O in async paths, missing typed failure for Intent ticker search, and CPU-heavy work running on the event loop. These issues degrade latency and observability across `intent`, `fundamental`, and `technical` agents.

## Goals
- Add typed failure surface for Intent ticker search.
- Offload sync I/O and CPU-heavy work from async paths.
- Keep changes minimal, sliceable, and test-backed.

## Non-Goals
- No functional redesign of LLM prompts or domain logic.
- No compatibility shims or long-lived re-exports.

## Findings
1. **Missing typed failure for ticker search** (`intent`): search provider returns bare list; failures are indistinguishable from empty results.
2. **Blocking market data fetch in async valuation** (`fundamental`): sync market data fetch includes retries and sleep in async workflow.
3. **Blocking retry sleep in market data service** (`fundamental`): uses `time.sleep` in retry loop (ok only if offloaded).
4. **CPU-heavy compute on event loop** (`technical`): fracdiff compute runs synchronously inside async use case.
5. **Sync network calls in intent search path** (`intent`): search provider calls are sync in workflow node path.

## Plan (Slices)
1. **Ticket 01 (small)**: Introduce `IntentTickerSearchResult` and update intent ticker search provider + orchestrator + tests to propagate failure/degrade info.
2. **Ticket 02 (small)**: Offload intent nodes that call sync LLM/network to threads (`extraction`, `searching`, `decision`, `clarification`) and update tests.
3. **Ticket 03 (small)**: Add async market data accessor (`get_market_snapshot_async`) and use it in fundamental valuation path.
4. **Ticket 04 (small)**: Offload fracdiff compute to background thread.

## Validation Gates
- `rg` legacy import/path sweeps for updated modules.
- Targeted tests per slice:
  - Intent: `finance-agent-core/tests/test_error_handling_intent.py`
  - Fundamental: relevant unit tests if present; otherwise regression via lint/rg
  - Technical: `finance-agent-core/tests/test_technical_analysis.py` (if relevant) or targeted use-case tests

## Rollback
Revert only the current slice if validation fails; keep slices atomic.
