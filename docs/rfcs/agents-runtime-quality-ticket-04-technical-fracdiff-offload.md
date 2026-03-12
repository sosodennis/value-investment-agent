# Ticket 04: Technical Fracdiff Offload

## Objective
Offload CPU-heavy fracdiff compute to thread to avoid blocking async loop.

## Scope
- `finance-agent-core/src/agents/technical/application/use_cases/run_fracdiff_compute_use_case.py`

## Changes
- Wrap `fracdiff_runtime.compute(...)` with `asyncio.to_thread`.

## Validation
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_analysis.py -q` (if present)
