"""Agent-owned wire projections for the Fundamental service boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.shared.internal_services import INTERNAL_CONTRACT_VERSION


class FundamentalIdentityResolutionRequestV1(BaseModel):
    """Agent-owned request projection for selected-ticker identity resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FundamentalIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    issuer_id: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    domicile: Literal["US"]
    reporting_basis: Literal["us-gaap"]
    security_id: str = Field(min_length=1)
    share_class: str = Field(min_length=1)
    currency: Literal["USD"]


class FundamentalIdentitySourceEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_id: Literal["sec-company-tickers", "sec-submissions", "sec-companyfacts"]
    source_uri: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    available_at: datetime
    media_type: Literal["application/json"]
    byte_count: int = Field(ge=0)

    @model_validator(mode="after")
    def timestamps_have_timezone(self) -> FundamentalIdentitySourceEvidenceV1:
        for name, value in (
            ("captured_at", self.captured_at),
            ("available_at", self.available_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        return self


class FundamentalIdentityResolutionV1(BaseModel):
    """Typed Agent projection of the service's verified identity result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    identity: FundamentalIdentityV1
    mapping_version: Literal["sec-issuer-identity-v1"]
    source_evidence: tuple[FundamentalIdentitySourceEvidenceV1, ...] = Field(
        min_length=3, max_length=3
    )
    resolution_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def response_is_bound_to_evidence(self) -> FundamentalIdentityResolutionV1:
        expected_source_ids = {
            "sec-company-tickers",
            "sec-submissions",
            "sec-companyfacts",
        }
        if {source.source_id for source in self.source_evidence} != expected_source_ids:
            raise ValueError("identity response requires all SEC source evidence")
        if (
            self.identity.security_id != self.ticker
            or self.identity.share_class != self.ticker
        ):
            raise ValueError("identity response must retain the selected ticker key")
        payload = self.model_dump(mode="json", exclude={"resolution_digest"})
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != self.resolution_digest:
            raise ValueError("resolution_digest does not bind identity evidence")
        return self


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


__all__ = [
    "FundamentalIdentityResolutionRequestV1",
    "FundamentalIdentityResolutionV1",
    "FundamentalIdentitySourceEvidenceV1",
    "FundamentalIdentityV1",
    "FundamentalServiceErrorV1",
    "FundamentalServiceResponseV1",
]
