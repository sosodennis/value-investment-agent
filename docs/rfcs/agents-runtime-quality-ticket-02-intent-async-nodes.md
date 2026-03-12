# Ticket 02: Intent Async Nodes Offload

## Objective
Avoid blocking the event loop by offloading sync LLM/network calls in intent nodes.

## Scope
- `finance-agent-core/src/workflow/nodes/intent_extraction/nodes.py`
- `finance-agent-core/tests/test_error_handling_intent.py`

## Changes
- Convert intent nodes to `async def` and call orchestrator methods via `asyncio.to_thread`.
- Update tests to `await` node calls.

## Validation
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_error_handling_intent.py -q`
