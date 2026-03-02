from __future__ import annotations

import pytest

from src.agents.debate.application.debate_llm_retry_service import (
    DebateLLMRetryPolicy,
    call_with_debate_llm_retry,
)


@pytest.mark.asyncio
async def test_call_with_debate_llm_retry_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    async def _execute() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError(
                "peer closed connection without sending complete message body (incomplete chunked read)"
            )
        return "ok"

    result = await call_with_debate_llm_retry(
        operation="unit_test_retryable",
        agent="BEAR_AGENT",
        round_num=2,
        execute=_execute,
        policy=DebateLLMRetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter_seconds=0.0,
        ),
    )

    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_call_with_debate_llm_retry_does_not_retry_non_retryable_error() -> None:
    attempts = {"count": 0}

    async def _execute() -> str:
        attempts["count"] += 1
        raise ValueError("invalid structured payload")

    with pytest.raises(ValueError, match="invalid structured payload"):
        await call_with_debate_llm_retry(
            operation="unit_test_non_retryable",
            agent="VERDICT",
            round_num=3,
            execute=_execute,
            policy=DebateLLMRetryPolicy(
                max_attempts=3,
                base_delay_seconds=0.0,
                max_delay_seconds=0.0,
                jitter_seconds=0.0,
            ),
        )

    assert attempts["count"] == 1
