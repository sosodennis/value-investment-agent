from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class FailureScope(StrEnum):
    KEY = "key"
    MODEL = "model"
    ACCOUNT = "account"
    WORKSPACE = "workspace"
    UPSTREAM_PROVIDER = "upstream_provider"
    UNKNOWN = "unknown"


class FailureCategory(StrEnum):
    AUTHENTICATION = "authentication"
    CREDIT = "credit"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    BAD_REQUEST = "bad_request"


@dataclass(frozen=True)
class UpstreamFailure:
    category: FailureCategory
    scope: FailureScope
    retryable: bool
    retry_after_seconds: float | None
    deployment_id: str | None
    http_status: int | None
    reason: str

    @property
    def rotates_key(self) -> bool:
        return self.scope is FailureScope.KEY


class RetryBudgetExhausted(RuntimeError):
    pass


@dataclass
class AttemptReservation:
    attempt: int
    timeout_seconds: float


@dataclass
class AttemptBudget:
    maximum_attempts: int
    deadline: float
    used_attempts: int = 0
    attempted_deployments: set[str] = field(default_factory=set)

    @classmethod
    def from_timeout(
        cls, maximum_attempts: int, timeout_seconds: float
    ) -> AttemptBudget:
        return cls(
            maximum_attempts=max(0, maximum_attempts),
            deadline=time.monotonic() + max(0.0, timeout_seconds),
        )

    def reserve(
        self, deployment_id: str, *, allow_repeat: bool = False
    ) -> AttemptReservation:
        remaining = self.deadline - time.monotonic()
        if self.used_attempts >= self.maximum_attempts or remaining <= 0:
            raise RetryBudgetExhausted
        if deployment_id in self.attempted_deployments and not allow_repeat:
            raise RetryBudgetExhausted
        self.used_attempts += 1
        self.attempted_deployments.add(deployment_id)
        return AttemptReservation(self.used_attempts, remaining)

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def delay_allowed(self, delay_seconds: float) -> bool:
        return delay_seconds >= 0 and delay_seconds < self.remaining_seconds()
