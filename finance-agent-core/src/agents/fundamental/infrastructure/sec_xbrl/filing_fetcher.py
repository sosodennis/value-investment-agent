from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from src.shared.kernel.tools.logger import get_logger, log_event

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
class SECFetchPolicy:
    max_attempts: int = _env_int("SEC_RETRY_MAX_ATTEMPTS", 4, minimum=1)
    base_delay_seconds: float = _env_float(
        "SEC_RETRY_BASE_DELAY_SECONDS",
        0.4,
        minimum=0.0,
    )
    max_delay_seconds: float = _env_float(
        "SEC_RETRY_MAX_DELAY_SECONDS",
        6.0,
        minimum=0.0,
    )
    jitter_seconds: float = _env_float(
        "SEC_RETRY_JITTER_SECONDS",
        0.25,
        minimum=0.0,
    )
    requests_per_second: float = _env_float(
        "SEC_REQUESTS_PER_SECOND",
        8.0,
        minimum=0.1,
    )


DEFAULT_SEC_FETCH_POLICY = SECFetchPolicy()


class _SecRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self._min_interval_seconds = 1.0 / max(0.1, requests_per_second)
        self._lock = threading.Lock()
        self._next_available_at = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_seconds = self._next_available_at - now
            if wait_seconds > 0:
                time.sleep(wait_seconds)
                now = time.monotonic()
            self._next_available_at = now + self._min_interval_seconds


_RATE_LIMITERS: dict[float, _SecRateLimiter] = {}
_RATE_LIMITERS_LOCK = threading.Lock()


def _get_rate_limiter(requests_per_second: float) -> _SecRateLimiter:
    key = round(max(0.1, requests_per_second), 3)
    with _RATE_LIMITERS_LOCK:
        limiter = _RATE_LIMITERS.get(key)
        if limiter is None:
            limiter = _SecRateLimiter(requests_per_second=key)
            _RATE_LIMITERS[key] = limiter
        return limiter


def _is_retryable_sec_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    message = str(exc).lower()
    retryable_tokens = (
        "429",
        "too many requests",
        "rate limit",
        "temporarily unavailable",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "502",
        "503",
        "504",
    )
    return any(token in message for token in retryable_tokens)


def _retry_delay_seconds(policy: SECFetchPolicy, attempt: int) -> float:
    exponential = policy.base_delay_seconds * (2 ** max(0, attempt - 1))
    capped = min(policy.max_delay_seconds, exponential)
    jitter = random.uniform(0.0, policy.jitter_seconds)
    return capped + jitter


def call_with_sec_retry(
    *,
    operation: str,
    ticker: str,
    execute: Callable[[], T],
    policy: SECFetchPolicy = DEFAULT_SEC_FETCH_POLICY,
) -> T:
    limiter = _get_rate_limiter(policy.requests_per_second)
    attempt = 0
    while attempt < policy.max_attempts:
        attempt += 1
        limiter.acquire()
        try:
            return execute()
        except Exception as exc:
            retryable = _is_retryable_sec_error(exc)
            if (not retryable) or attempt >= policy.max_attempts:
                raise
            sleep_seconds = _retry_delay_seconds(policy, attempt)
            log_event(
                logger,
                event="fundamental_sec_fetch_retry",
                message="sec fetch failed; retrying with backoff",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_SEC_FETCH_RETRY",
                fields={
                    "ticker": ticker,
                    "operation": operation,
                    "attempt": attempt,
                    "max_attempts": policy.max_attempts,
                    "retry_in_seconds": round(sleep_seconds, 3),
                    "exception": str(exc),
                },
            )
            time.sleep(sleep_seconds)
    raise RuntimeError("SEC fetch retry loop reached unreachable state")
