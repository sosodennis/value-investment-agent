"""Small, explicit runtime controls for the Fundamental service boundary.

The service keeps no valuation-operation state here.  The state in this module is
limited to short-lived request controls and process metrics; released data and
calculation evidence remain in the immutable stores owned by the service.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final

from fastapi import Request

AUTH_HEADER: Final[str] = "Authorization"
CORRELATION_HEADER: Final[str] = "X-Correlation-ID"
DEADLINE_HEADER: Final[str] = "X-Request-Deadline"
TIMEOUT_HEADER: Final[str] = "X-Request-Timeout-Ms"


class ServiceError(RuntimeError):
    """An error safe to expose through the stable internal error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class OperationsConfig:
    """Environment-backed limits and credentials for one service process."""

    auth_token: str | None = None
    signing_key: str | None = None
    require_auth: bool = True
    max_body_bytes: int = 2_000_000
    max_calculation_samples: int = 10_000
    max_forecast_periods: int = 30
    max_request_ms: int = 5_000
    rate_limit_per_minute: int = 120

    @classmethod
    def testing(cls) -> OperationsConfig:
        """A deliberately unauthenticated config for direct unit-test seams."""
        return cls(require_auth=False, rate_limit_per_minute=10_000)

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

        require_auth = os.getenv("FUNDAMENTAL_SERVICE_REQUIRE_AUTH", "true").lower()
        if require_auth not in {"true", "false"}:
            raise ValueError("FUNDAMENTAL_SERVICE_REQUIRE_AUTH must be true or false")
        return cls(
            auth_token=os.getenv("FUNDAMENTAL_SERVICE_AUTH_TOKEN"),
            signing_key=os.getenv("FUNDAMENTAL_SERVICE_SIGNING_KEY"),
            require_auth=require_auth == "true",
            max_body_bytes=integer("FUNDAMENTAL_SERVICE_MAX_BODY_BYTES", 2_000_000),
            max_calculation_samples=integer(
                "FUNDAMENTAL_SERVICE_MAX_CALCULATION_SAMPLES", 10_000
            ),
            max_forecast_periods=integer(
                "FUNDAMENTAL_SERVICE_MAX_FORECAST_PERIODS", 30
            ),
            max_request_ms=integer("FUNDAMENTAL_SERVICE_MAX_REQUEST_MS", 5_000),
            rate_limit_per_minute=integer(
                "FUNDAMENTAL_SERVICE_RATE_LIMIT_PER_MINUTE", 120
            ),
        )

    @property
    def auth_ready(self) -> bool:
        return not self.require_auth or bool(self.auth_token and self.signing_key)


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


def _parse_deadline(value: str) -> datetime:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError) as exc:
            raise ServiceError(
                "REQUEST_DEADLINE_INVALID",
                "request deadline is invalid",
                status_code=400,
                retryable=False,
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ServiceError(
            "REQUEST_DEADLINE_INVALID",
            "request deadline must include a timezone",
            status_code=400,
            retryable=False,
        )
    return parsed.astimezone(UTC)


def enforce_deadline(request: Request, config: OperationsConfig) -> datetime | None:
    deadline_header = request.headers.get(DEADLINE_HEADER)
    timeout_header = request.headers.get(TIMEOUT_HEADER)
    deadline = _parse_deadline(deadline_header) if deadline_header else None
    if timeout_header:
        try:
            timeout_ms = int(timeout_header)
        except ValueError as exc:
            raise ServiceError(
                "REQUEST_DEADLINE_INVALID",
                "request timeout is invalid",
                status_code=400,
                retryable=False,
            ) from exc
        if timeout_ms < 1:
            raise ServiceError(
                "REQUEST_DEADLINE_INVALID",
                "request timeout must be positive",
                status_code=400,
                retryable=False,
            )
        requested = datetime.now(UTC).timestamp() + timeout_ms / 1000
        candidate = datetime.fromtimestamp(requested, UTC)
        deadline = candidate if deadline is None else min(deadline, candidate)
    if deadline is not None and deadline <= datetime.now(UTC):
        raise ServiceError(
            "REQUEST_DEADLINE_EXCEEDED",
            "request deadline has expired",
            status_code=408,
            retryable=True,
        )
    if deadline is not None:
        remaining_ms = int((deadline - datetime.now(UTC)).total_seconds() * 1000)
        if remaining_ms > config.max_request_ms:
            deadline = datetime.now(UTC).timestamp() + config.max_request_ms / 1000
            deadline = datetime.fromtimestamp(deadline, UTC)
    return deadline


def authenticate(request: Request, config: OperationsConfig) -> str:
    if not config.require_auth:
        return "test"
    if not config.auth_ready:
        raise ServiceError(
            "DEPENDENCY_INCOMPATIBLE",
            "service authentication is not configured",
            status_code=503,
            retryable=False,
        )
    header = request.headers.get(AUTH_HEADER, "")
    scheme, _, token = header.partition(" ")
    if (
        scheme.lower() != "bearer"
        or not token
        or not hmac.compare_digest(token, config.auth_token or "")
    ):
        raise ServiceError(
            "AUTHENTICATION_FAILED",
            "authentication failed",
            status_code=401,
            retryable=False,
        )
    return "internal"


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
