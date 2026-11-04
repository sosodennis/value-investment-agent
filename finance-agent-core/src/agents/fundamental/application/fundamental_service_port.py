"""Typed port for the independently deployed Fundamental service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol

from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalServiceResponseV1,
)
from src.shared.internal_services import InternalPrincipal

FundamentalOperation = Literal["validate", "calculate", "uncertainty", "replay"]


class FundamentalServiceFailure(RuntimeError):
    """A typed unavailable/degraded outcome from the service boundary."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class FundamentalServiceClient(Protocol):
    """Caller-owned transport port; no Fundamental implementation dependency."""

    async def execute(
        self,
        operation: FundamentalOperation,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalServiceResponseV1: ...


__all__ = [
    "FundamentalOperation",
    "FundamentalServiceClient",
    "FundamentalServiceFailure",
]
