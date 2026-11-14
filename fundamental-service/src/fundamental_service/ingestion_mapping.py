"""Mapping resolution at the validated-original ingestion boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    IdentityV1,
    IssueV1,
    SecCapturedSourceEvidenceV1,
    SecIntegrityEvidenceV1,
    StrictModel,
)
from .facts import CanonicalMappingV1
from .original_issuer import OriginalIssuerEvidenceV1


@dataclass(frozen=True)
class ValidatedOriginalV1:
    identity: IdentityV1
    original: OriginalIssuerEvidenceV1
    integrity: SecIntegrityEvidenceV1
    captured_sources: tuple[SecCapturedSourceEvidenceV1, ...]
    primary_media_type: str


class IngestionMappingResolutionV1(StrictModel):
    mappings: tuple[CanonicalMappingV1, ...]
    evidence_ref: str
    missing_fields: tuple[str, ...]
    issues: tuple[IssueV1, ...]


class IngestionMappingResolverPort(Protocol):
    def resolve(
        self, validated: ValidatedOriginalV1
    ) -> IngestionMappingResolutionV1: ...
