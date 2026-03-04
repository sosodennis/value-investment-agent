from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)

T = TypeVar("T")


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class DebateLLMRetryPolicy:
    max_attempts: int = _env_int("DEBATE_LLM_RETRY_MAX_ATTEMPTS", 3, minimum=1)
    base_delay_seconds: float = _env_float(
        "DEBATE_LLM_RETRY_BASE_DELAY_SECONDS",
        0.8,
        minimum=0.0,
    )
    max_delay_seconds: float = _env_float(
        "DEBATE_LLM_RETRY_MAX_DELAY_SECONDS",
        8.0,
        minimum=0.0,
    )
    jitter_seconds: float = _env_float(
        "DEBATE_LLM_RETRY_JITTER_SECONDS",
        0.4,
        minimum=0.0,
    )


DEFAULT_DEBATE_LLM_RETRY_POLICY = DebateLLMRetryPolicy()


def _is_retryable_llm_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_tokens = (
        "incomplete chunked read",
        "peer closed connection",
        "read operation timed out",
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "502",
        "503",
        "504",
        "rate limit",
        "too many requests",
        "429",
    )
    return any(token in message for token in retryable_tokens)


def _retry_delay_seconds(policy: DebateLLMRetryPolicy, attempt: int) -> float:
    exponential = policy.base_delay_seconds * (2 ** max(0, attempt - 1))
    capped = min(policy.max_delay_seconds, exponential)
    jitter = random.uniform(0.0, policy.jitter_seconds)
    return capped + jitter


async def call_with_debate_llm_retry(
    *,
    operation: str,
    agent: str,
    round_num: int,
    execute: Callable[[], Awaitable[T]],
    policy: DebateLLMRetryPolicy = DEFAULT_DEBATE_LLM_RETRY_POLICY,
) -> T:
    attempt = 0
    while attempt < policy.max_attempts:
        attempt += 1
        try:
            return await execute()
        except Exception as exc:
            retryable = _is_retryable_llm_error(exc)
            if (not retryable) or attempt >= policy.max_attempts:
                raise
            sleep_seconds = _retry_delay_seconds(policy, attempt)
            exc_text = bounded_text(exc)
            log_event(
                logger,
                event="debate_llm_retry",
                message="debate llm call failed; retrying",
                error_code="DEBATE_LLM_RETRY",
                fields={
                    "operation": operation,
                    "agent": agent,
                    "round_num": round_num,
                    "attempt": attempt,
                    "max_attempts": policy.max_attempts,
                    "retry_in_seconds": round(sleep_seconds, 3),
                    "exception": exc_text,
                },
            )
            await asyncio.sleep(sleep_seconds)
    raise RuntimeError("debate llm retry loop reached unreachable state")
