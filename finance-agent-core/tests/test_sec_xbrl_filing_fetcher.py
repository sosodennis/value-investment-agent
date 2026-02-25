from __future__ import annotations

import pytest

import src.agents.fundamental.data.clients.sec_xbrl.filing_fetcher as m
from src.agents.fundamental.data.clients.sec_xbrl.filing_fetcher import (
    SECFetchPolicy,
    call_with_sec_retry,
)


class _NoopLimiter:
    def acquire(self) -> None:
        return None


def test_call_with_sec_retry_retries_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}
    monkeypatch.setattr(m, "_get_rate_limiter", lambda _rps: _NoopLimiter())
    monkeypatch.setattr(m.time, "sleep", lambda _seconds: None)

    def flaky_call() -> int:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("429 too many requests")
        return 7

    policy = SECFetchPolicy(
        max_attempts=3,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
        jitter_seconds=0.0,
        requests_per_second=1000.0,
    )
    result = call_with_sec_retry(
        operation="unit_test_retryable",
        ticker="AAPL",
        execute=flaky_call,
        policy=policy,
    )
    assert result == 7
    assert attempts["count"] == 3


def test_call_with_sec_retry_does_not_retry_non_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}
    monkeypatch.setattr(m, "_get_rate_limiter", lambda _rps: _NoopLimiter())

    def bad_call() -> int:
        attempts["count"] += 1
        raise ValueError("schema mismatch")

    policy = SECFetchPolicy(
        max_attempts=4,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
        jitter_seconds=0.0,
        requests_per_second=1000.0,
    )
    with pytest.raises(ValueError):
        call_with_sec_retry(
            operation="unit_test_non_retryable",
            ticker="AAPL",
            execute=bad_call,
            policy=policy,
        )
    assert attempts["count"] == 1
