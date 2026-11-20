"""Bounded, process-local coordination for identical calculator work."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from pydantic import ValidationError

from .calculator import CALCULATOR_RESULT_VERSION
from .contracts import CalculationArtifactV1, ValuationInputV1
from .operations import ServiceError, guard_execution_deadline
from .serialization import canonical_bytes, sha256_digest


@dataclass(frozen=True, slots=True)
class ImmutableCalculationResult:
    """Canonical calculator output detached from request-owned mutable state."""

    input_digest: str
    semantics_digest: str
    artifact_bytes: bytes

    @classmethod
    def capture(
        cls,
        calculation_input: ValuationInputV1,
        *,
        allow_provisional: bool,
        artifact: CalculationArtifactV1,
    ) -> ImmutableCalculationResult:
        input_digest = sha256_digest(
            calculation_input.model_dump(exclude={"input_digest", "caller_approval"})
        )
        if (
            calculation_input.input_digest not in (None, input_digest)
            or artifact.input_digest != input_digest
            or artifact.calculation_version != CALCULATOR_RESULT_VERSION
        ):
            raise ValueError("calculator output does not match its exact input")
        return cls(
            input_digest=input_digest,
            semantics_digest=_semantics_digest(input_digest, allow_provisional),
            artifact_bytes=canonical_bytes(artifact),
        )

    def materialize(
        self,
        calculation_input: ValuationInputV1,
        *,
        allow_provisional: bool,
    ) -> CalculationArtifactV1 | None:
        input_digest = sha256_digest(
            calculation_input.model_dump(exclude={"input_digest", "caller_approval"})
        )
        if (
            calculation_input.input_digest not in (None, input_digest)
            or self.input_digest != input_digest
            or self.semantics_digest
            != _semantics_digest(input_digest, allow_provisional)
        ):
            return None
        try:
            artifact = CalculationArtifactV1.model_validate_json(self.artifact_bytes)
        except (ValidationError, ValueError):
            return None
        if (
            artifact.input_digest != input_digest
            or artifact.calculation_version != CALCULATOR_RESULT_VERSION
        ):
            return None
        return artifact


def _semantics_digest(input_digest: str, allow_provisional: bool) -> str:
    return sha256_digest(
        {
            "calculator_result_version": CALCULATOR_RESULT_VERSION,
            "input_digest": input_digest,
            "allow_provisional": allow_provisional,
        }
    )


@dataclass(slots=True)
class _Flight:
    key: str
    result: Future[ImmutableCalculationResult | None]
    participants: int = 1


class CalculationFlightLease:
    """One request's independent claim on an active calculation flight."""

    def __init__(
        self,
        registry: CalculationFlightRegistry,
        flight: _Flight,
        *,
        owner: bool,
    ) -> None:
        self._registry = registry
        self._flight = flight
        self.is_owner = owner
        self._closed = False

    async def wait(self, deadline_at: datetime) -> ImmutableCalculationResult | None:
        guard_execution_deadline(deadline_at)
        remaining_seconds = (deadline_at - datetime.now(UTC)).total_seconds()
        wrapped = asyncio.wrap_future(self._flight.result)
        try:
            return await asyncio.wait_for(
                asyncio.shield(wrapped), timeout=remaining_seconds
            )
        except asyncio.TimeoutError as error:
            raise ServiceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "request deadline expired while waiting for identical calculation",
                status_code=408,
                retryable=True,
            ) from error

    def publish(
        self,
        artifact: CalculationArtifactV1,
        calculation_input: ValuationInputV1,
        allow_provisional: bool,
        deadline_at: datetime | None,
    ) -> None:
        if self.is_owner:
            self._registry._publish(
                self._flight,
                artifact,
                calculation_input,
                allow_provisional=allow_provisional,
                deadline_at=deadline_at,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.is_owner:
            self._registry._finish(self._flight)
        self._registry._release(self._flight)


class CalculationFlightRegistry:
    """App-scoped active-only registry; it never retains completed results."""

    def __init__(
        self,
        *,
        max_active_flights: int = 8,
        max_participants_per_flight: int = 4,
        max_active_participants: int = 32,
    ) -> None:
        if (
            max_active_flights < 1
            or max_participants_per_flight < 1
            or max_active_participants < 1
        ):
            raise ValueError("calculation flight bounds must be positive")
        self.runtime_identity = uuid4().hex
        self._max_active_flights = max_active_flights
        self._max_participants_per_flight = max_participants_per_flight
        self._max_active_participants = max_active_participants
        self._active_participants = 0
        self._lock = Lock()
        self._flights: dict[str, _Flight] = {}
        self._closed = False

    def join(self, key: str) -> CalculationFlightLease | None:
        with self._lock:
            if self._closed:
                return None
            existing = self._flights.get(key)
            if existing is not None:
                if existing.result.done():
                    self._flights.pop(key, None)
                elif (
                    existing.participants < self._max_participants_per_flight
                    and self._active_participants < self._max_active_participants
                ):
                    existing.participants += 1
                    self._active_participants += 1
                    return CalculationFlightLease(self, existing, owner=False)
                else:
                    return None
            if (
                len(self._flights) >= self._max_active_flights
                or self._active_participants >= self._max_active_participants
            ):
                return None
            flight = _Flight(key=key, result=Future())
            self._flights[key] = flight
            self._active_participants += 1
            return CalculationFlightLease(self, flight, owner=True)

    def _publish(
        self,
        flight: _Flight,
        artifact: CalculationArtifactV1,
        calculation_input: ValuationInputV1,
        *,
        allow_provisional: bool,
        deadline_at: datetime | None,
    ) -> None:
        with self._lock:
            if flight.result.done():
                self._remove_if_current(flight)
                return
            if flight.participants <= 1:
                self._remove_if_current(flight)
                _resolve(flight.result, None)
                return

        try:
            candidate = ImmutableCalculationResult.capture(
                calculation_input,
                allow_provisional=allow_provisional,
                artifact=artifact,
            )
        except (TypeError, ValueError, ValidationError):
            candidate = None
        if candidate is not None:
            try:
                guard_execution_deadline(deadline_at)
            except ServiceError:
                candidate = None

        with self._lock:
            self._remove_if_current(flight)
            _resolve(flight.result, candidate)

    def _finish(self, flight: _Flight) -> None:
        with self._lock:
            self._remove_if_current(flight)
        _resolve(flight.result, None)

    def _release(self, flight: _Flight) -> None:
        with self._lock:
            flight.participants = max(0, flight.participants - 1)
            self._active_participants = max(0, self._active_participants - 1)

    def _remove_if_current(self, flight: _Flight) -> None:
        if self._flights.get(flight.key) is flight:
            self._flights.pop(flight.key, None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            flights = tuple(self._flights.values())
            self._flights.clear()
        for flight in flights:
            _resolve(flight.result, None)


def _resolve(
    future: Future[ImmutableCalculationResult | None],
    result: ImmutableCalculationResult | None,
) -> None:
    try:
        if not future.done():
            future.set_result(result)
    except InvalidStateError:
        # A concurrent shutdown or owner cleanup has already resolved the flight.
        pass
