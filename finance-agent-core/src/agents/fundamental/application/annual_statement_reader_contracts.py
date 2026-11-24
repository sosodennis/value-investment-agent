"""Authenticated workspace read intents and deployment catalog projections."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.artifacts.public import ArtifactReference


class AnnualStatementCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    company_name: str = Field(min_length=1)
    cutoff_at: AwareDatetime


class AnnualStatementReaderBinding(AnnualStatementCatalogEntry):
    profile_id: str = Field(min_length=1, max_length=256)
    security_id: str | None = None
    security_scope: str = "issuer"


class AnnualStatementCatalogResponse(BaseModel):
    entries: tuple[AnnualStatementCatalogEntry, ...]


class AnnualStatementExistingThreadReadIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["existing_thread"]
    thread_id: str = Field(min_length=1, max_length=128)
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")


class AnnualStatementNewThreadReadIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["new_thread"]
    creation_id: UUID
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")


AnnualStatementReadIntent = Annotated[
    AnnualStatementExistingThreadReadIntent | AnnualStatementNewThreadReadIntent,
    Field(discriminator="kind"),
]


class AnnualStatementArtifactResponse(BaseModel):
    thread_id: str
    reference: ArtifactReference


class AnnualStatementReadFailure(BaseModel):
    code: str
    message: str
    retryable: bool


class AnnualStatementReadErrorResponse(BaseModel):
    detail: AnnualStatementReadFailure
