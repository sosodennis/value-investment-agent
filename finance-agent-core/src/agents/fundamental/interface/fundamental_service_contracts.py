"""Agent-owned wire projections for the Fundamental service boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.internal_services import INTERNAL_CONTRACT_VERSION


class FundamentalServiceResponseV1(BaseModel):
    """Shared response metadata plus an opaque, service-owned result projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    schema_version: Literal["fundamental.v1"]
    result: dict[str, object]


class FundamentalServiceErrorV1(BaseModel):
    """Stable error projection used by the typed client implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    error: dict[str, object]


__all__ = ["FundamentalServiceErrorV1", "FundamentalServiceResponseV1"]
