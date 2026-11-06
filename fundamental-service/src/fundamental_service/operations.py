"""Small, explicit runtime controls for the Fundamental service boundary.

The service keeps no valuation-operation state here.  The state in this module is
limited to short-lived request controls and process metrics; released data and
calculation evidence remain in the immutable stores owned by the service.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from fastapi import Request

AUTH_HEADER: Final[str] = "Authorization"
CORRELATION_HEADER: Final[str] = "X-Correlation-ID"


class ServiceError(RuntimeError):
    """An error safe to expose through the stable internal error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms


@dataclass(frozen=True)
class OperationsConfig:
    """Environment-backed limits and credentials for one service process."""

    service_token: str | None = None
    max_body_bytes: int = 2_000_000
    max_calculation_samples: int = 10_000
    max_forecast_periods: int = 30
    max_request_ms: int = 5_000
    max_ingestion_ms: int = 120_000
    rate_limit_per_minute: int = 120
    ingestion_rate_limit_per_minute: int = 10
    ingestion_authorized_organizations: frozenset[str] = frozenset()

    @classmethod
    def testing(cls) -> OperationsConfig:
        """A deterministic token for direct unit-test seams.

        Tests still exercise the production authentication path and must create a
        signed ``InternalRequestContext``; there is no unauthenticated bypass.
        """
        return cls(service_token="test-service-token", rate_limit_per_minute=10_000)

    @classmethod
    def from_env(cls) -> OperationsConfig:
        def integer(name: str, default: int, *, minimum: int = 1) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc
            if value < minimum:
                raise ValueError(f"{name} must be at least {minimum}")
            return value

        return cls(
            service_token=os.getenv("FUNDAMENTAL_SERVICE_TOKEN"),
            max_body_bytes=integer("FUNDAMENTAL_SERVICE_MAX_BODY_BYTES", 2_000_000),
            max_calculation_samples=integer(
                "FUNDAMENTAL_SERVICE_MAX_CALCULATION_SAMPLES", 10_000
            ),
            max_forecast_periods=integer(
                "FUNDAMENTAL_SERVICE_MAX_FORECAST_PERIODS", 30
            ),
            max_request_ms=integer("FUNDAMENTAL_SERVICE_MAX_REQUEST_MS", 5_000),
            max_ingestion_ms=integer("FUNDAMENTAL_SERVICE_MAX_INGESTION_MS", 120_000),
            rate_limit_per_minute=integer(
                "FUNDAMENTAL_SERVICE_RATE_LIMIT_PER_MINUTE", 120
            ),
            ingestion_rate_limit_per_minute=integer(
                "FUNDAMENTAL_SERVICE_INGESTION_RATE_LIMIT_PER_MINUTE", 10
            ),
            ingestion_authorized_organizations=frozenset(
                item.strip()
                for item in os.getenv(
                    "FUNDAMENTAL_SERVICE_INGESTION_ORGANIZATIONS", ""
                ).split(",")
                if item.strip()
            ),
        )

    @property
    def auth_ready(self) -> bool:
        return bool(self.service_token)


class OperationalMetrics:
    """Bounded in-process counters; no request or valuation payloads are stored."""

    _KNOWN_COUNTERS: Final[tuple[str, ...]] = (
        "requests_total",
        "request_failures_total",
        "auth_failures_total",
        "rate_limited_total",
        "deadline_failures_total",
        "calculation_budget_failures_total",
        "calculation_latency_ms_total",
        "source_health_failures_total",
        "snapshot_freshness_failures_total",
        "cache_hit_total",
        "cache_miss_total",
        "cache_stale_total",
        "quality_status_total",
        "abstention_total",
        "provenance_replay_failures_total",
        "provider_degradation_total",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)

    def increment(self, name: str, value: int = 1) -> None:
        if value < 0:
            raise ValueError("metric increments cannot be negative")
        with self._lock:
            self._counters[name] += value

    def observe_request(self, *, status_code: int, elapsed_ms: float) -> None:
        self.increment("requests_total")
        self.increment("request_failures_total", int(status_code >= 400))
        self.increment("calculation_latency_ms_total", int(max(0, elapsed_ms)))

    def render_prometheus(self) -> str:
        with self._lock:
            values = dict(self._counters)
        lines = [
            "# HELP fundamental_service_requests_total HTTP requests handled.",
            "# TYPE fundamental_service_requests_total counter",
        ]
        for name in self._KNOWN_COUNTERS:
            lines.append(f"fundamental_service_{name} {values.get(name, 0)}")
        for name, value in sorted(values.items()):
            if name in self._KNOWN_COUNTERS:
                continue
            lines.append(f"fundamental_service_{name} {value}")
        return "\n".join(lines) + "\n"


class RateLimiter:
    """A short-lived process limiter, separate from valuation and artifact state."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


def correlation_id(request: Request) -> str:
    value = request.headers.get(CORRELATION_HEADER)
    if value and len(value) <= 128 and all(char.isprintable() for char in value):
        return value
    # Imported lazily so the hot path does not allocate UUID state for callers
    # that already supplied a correlation identifier.
    from uuid import uuid4

    return str(uuid4())


def enforce_deadline(
    deadline_at: datetime,
    config: OperationsConfig,
    *,
    max_request_ms: int | None = None,
) -> datetime:
    """Validate the caller's absolute deadline without restarting its budget."""
    now = datetime.now(UTC)
    if deadline_at <= now:
        raise ServiceError(
            "REQUEST_DEADLINE_EXCEEDED",
            "request deadline has expired",
            status_code=408,
            retryable=True,
        )
    # Keep a local process budget while preserving the original absolute context
    # deadline for downstream propagation and response correlation.
    budget_ms = config.max_request_ms if max_request_ms is None else max_request_ms
    return min(deadline_at, now + timedelta(milliseconds=budget_ms))


def guard_body_size(request: Request, config: OperationsConfig) -> None:
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ServiceError(
            "REQUEST_BODY_INVALID",
            "request body length is invalid",
            status_code=400,
            retryable=False,
        ) from exc
    if length > config.max_body_bytes:
        raise ServiceError(
            "CALCULATION_BUDGET_EXCEEDED",
            "request body exceeds the synchronous service budget",
            status_code=413,
            retryable=False,
        )


def guard_calculation_budget(request: object, config: OperationsConfig) -> None:
    assumptions = getattr(request, "assumptions", None)
    forecast = getattr(assumptions, "forecast", None)
    periods = len(getattr(forecast, "revenue_growth", ()))
    if periods > config.max_forecast_periods:
        raise ServiceError(
            "CALCULATION_BUDGET_EXCEEDED",
            "forecast exceeds the synchronous service budget",
            status_code=422,
            retryable=False,
        )
    samples = getattr(getattr(request, "uncertainty", None), "samples", None)
    monte_carlo = getattr(request, "monte_carlo", None)
    if monte_carlo is not None:
        samples = getattr(getattr(monte_carlo, "uncertainty", None), "samples", samples)
    if samples is not None and samples > config.max_calculation_samples:
        raise ServiceError(
            "CALCULATION_BUDGET_EXCEEDED",
            "requested samples exceed the synchronous service budget",
            status_code=422,
            retryable=False,
        )
