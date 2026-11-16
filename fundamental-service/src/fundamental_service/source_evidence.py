"""Original source evidence shared by macro and reference providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True)
class RetainedSourceV1:
    """Original bytes and acquisition identity passed to a source provider."""

    source_id: str
    uri: str
    source_version: str
    terms_reference: str
    content: bytes
    captured_at: datetime


class SourceArtifactV1(BaseModel):
    """Digest-only provenance for one immutable provider source artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime

    @model_validator(mode="after")
    def timezone_required(self) -> SourceArtifactV1:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("source capture time must include a timezone")
        return self
