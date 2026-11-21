"""Bounded, process-local coordination for identical valuation preparation."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from pydantic import ValidationError

from .operations import ServiceError, guard_execution_deadline
from .serialization import canonical_bytes, sha256_digest
from .valuation_preparation import AutomaticValuationPreparationV1


@dataclass(frozen=True, slots=True)
class ImmutableAutomaticValuationPreparation:
    """Canonical preparation bytes detached from request-owned mutable state."""

    preparation_digest: str
    input_digest: str
    preparation_bytes: bytes

    @classmethod
    def capture(
        cls,
        preparation: AutomaticValuationPreparationV1,
        *,
        expected_input_digest: str,
    ) -> ImmutableAutomaticValuationPreparation:
        value = preparation.input
        if preparation.status != "prepared" or value is None:
            raise ValueError("only a complete preparation can join a flight")
        input_digest = sha256_digest(
            value.model_dump(exclude={"input_digest", "caller_approval"})
        )
        if (
            value.input_digest != input_digest
            or input_digest != expected_input_digest
            or value.caller_approval is not None
        ):
            raise ValueError("preparation does not match its exact input")
        return cls(
            preparation_digest=sha256_digest(preparation),
            input_digest=input_digest,
            preparation_bytes=canonical_bytes(preparation),
        )

    def materialize(
        self, *, expected_input_digest: str
    ) -> AutomaticValuationPreparationV1 | None:
        try:
            preparation = AutomaticValuationPreparationV1.model_validate_json(
                self.preparation_bytes
            )
        except (ValidationError, ValueError):
            return None
        value = preparation.input
        if (
            preparation.status != "prepared"
            or value is None
            or sha256_digest(preparation) != self.preparation_digest
        ):
            return None
        input_digest = sha256_digest(
            value.model_dump(exclude={"input_digest", "caller_approval"})
        )
        if (
            value.input_digest != input_digest
            or self.input_digest != input_digest
            or expected_input_digest != input_digest
            or value.caller_approval is not None
        ):
            return None
        return preparation


@dataclass(slots=True)
class _Flight:
    key: str
    result: Future[ImmutableAutomaticValuationPreparation | None]
    ready: asyncio.Event
    loop: asyncio.AbstractEventLoop | None = None
    participants: int = 1


class AutomaticValuationFlightLease:
    """One request's independent claim on an active preparation flight."""

    def __init__(
        self,
        registry: AutomaticValuationFlightRegistry,
        flight: _Flight,
        *,
        owner: bool,
    ) -> None:
        self._registry = registry
        self._flight = flight
        self.is_owner = owner
        self._closed = False

    async def wait(
        self, deadline_at: datetime
    ) -> ImmutableAutomaticValuationPreparation | None:
        guard_execution_deadline(deadline_at)
        remaining_seconds = (deadline_at - datetime.now(UTC)).total_seconds()
        with self._registry._lock:
            self._flight.loop = asyncio.get_running_loop()
            if self._flight.result.done():
                return self._flight.result.result()
        try:
            await asyncio.wait_for(self._flight.ready.wait(), timeout=remaining_seconds)
        except asyncio.TimeoutError as error:
            raise ServiceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "request deadline expired while waiting for identical preparation",
                status_code=408,
                retryable=True,
            ) from error
        return self._flight.result.result()

    def publish(
        self,
        preparation: AutomaticValuationPreparationV1,
        expected_input_digest: str,
        deadline_at: datetime | None,
    ) -> None:
        if self.is_owner:
            self._registry._publish(
                self._flight,
                preparation,
                expected_input_digest=expected_input_digest,
                deadline_at=deadline_at,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.is_owner:
            self._registry._finish(self._flight)
        self._registry._release(self._flight)


class AutomaticValuationFlightRegistry:
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
            raise ValueError("valuation flight bounds must be positive")
        self.runtime_identity = uuid4().hex
        self._max_active_flights = max_active_flights
        self._max_participants_per_flight = max_participants_per_flight
        self._max_active_participants = max_active_participants
        self._active_participants = 0
        self._lock = Lock()
        self._flights: dict[str, _Flight] = {}
        self._closed = False

    def join(self, key: str) -> AutomaticValuationFlightLease | None:
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
                    return AutomaticValuationFlightLease(self, existing, owner=False)
                else:
                    return None
            if (
                len(self._flights) >= self._max_active_flights
                or self._active_participants >= self._max_active_participants
            ):
                return None
            flight = _Flight(key=key, result=Future(), ready=asyncio.Event())
            self._flights[key] = flight
            self._active_participants += 1
            return AutomaticValuationFlightLease(self, flight, owner=True)

    def _publish(
        self,
        flight: _Flight,
        preparation: AutomaticValuationPreparationV1,
        *,
        expected_input_digest: str,
        deadline_at: datetime | None,
    ) -> None:
        with self._lock:
            if flight.result.done():
                self._remove_if_current(flight)
                return
            if flight.participants <= 1:
                self._remove_if_current(flight)
                candidate = None
            else:
                candidate = preparation

        if candidate is None:
            immutable = None
        else:
            try:
                immutable = ImmutableAutomaticValuationPreparation.capture(
                    candidate, expected_input_digest=expected_input_digest
                )
                guard_execution_deadline(deadline_at)
            except (ServiceError, TypeError, ValueError, ValidationError):
                immutable = None

        with self._lock:
            self._remove_if_current(flight)
        _resolve(flight.result, immutable)
        self._notify(flight)

    def _finish(self, flight: _Flight) -> None:
        with self._lock:
            self._remove_if_current(flight)
        _resolve(flight.result, None)
        self._notify(flight)

    def _release(self, flight: _Flight) -> None:
        with self._lock:
            flight.participants = max(0, flight.participants - 1)
            self._active_participants = max(0, self._active_participants - 1)

    def _remove_if_current(self, flight: _Flight) -> None:
        if self._flights.get(flight.key) is flight:
            self._flights.pop(flight.key, None)

    def _notify(self, flight: _Flight) -> None:
        with self._lock:
            loop = flight.loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(flight.ready.set)
        except RuntimeError:
            pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            flights = tuple(self._flights.values())
            self._flights.clear()
        for flight in flights:
            _resolve(flight.result, None)
            self._notify(flight)


def _resolve(
    future: Future[ImmutableAutomaticValuationPreparation | None],
    result: ImmutableAutomaticValuationPreparation | None,
) -> None:
    try:
        if not future.done():
            future.set_result(result)
    except InvalidStateError:
        pass
