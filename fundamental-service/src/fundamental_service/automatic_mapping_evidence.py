"""Validate shared immutable source evidence within one mapping operation."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .data_releases import DataReleaseError
from .issuer_identity import IdentityResolutionError, validate_original_filing_identity
from .issuer_release_evidence import verify_original_bytes, verify_original_integrity
from .original_issuer import OriginalIssuerEvidenceChecks
from .serialization import sha256_digest
from .taxonomy_evidence import require_original_taxonomy

if TYPE_CHECKING:
    from .automatic_mapping import AutomaticMappingSourceV1


class AutomaticMappingEvidenceChecks:
    """Share source checks, never proposal decisions or cross-operation state."""

    def __init__(self) -> None:
        self._checked: dict[str, tuple[str, ...]] = {}
        self.originals = OriginalIssuerEvidenceChecks()

    def assess(
        self, request: AutomaticMappingSourceV1, *, contents: dict[str, bytes]
    ) -> tuple[str, ...]:
        key = sha256_digest(
            (
                request.source_revision,
                request.evaluator_id,
                request.original,
                request.integrity,
                request.evidence_refs,
                request.security_identity,
                tuple(
                    (name, hashlib.sha256(raw).hexdigest())
                    for name, raw in sorted(contents.items())
                ),
            )
        )
        if key not in self._checked:
            self._checked[key] = _source_reasons(request, contents=contents)
        return self._checked[key]


def _source_reasons(
    request: AutomaticMappingSourceV1, *, contents: dict[str, bytes]
) -> tuple[str, ...]:
    original = request.original
    reasons = set(original.issue_codes) if original.status != "matched" else set()
    try:
        for ref in request.evidence_refs:
            if (
                ref.content_hash not in contents
                or hashlib.sha256(contents[ref.content_hash]).hexdigest()
                != ref.content_hash
            ):
                raise DataReleaseError(
                    "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE",
                    "automatic mapping requires its retained evidence bytes",
                )
        require_original_taxonomy(
            original.report.taxonomy_cache_hash or "", request.evidence_refs, contents
        )
        verify_original_integrity(
            original, request.integrity, parser_version=original.report.parser_version
        )
        verify_original_bytes(request.integrity, contents)
    except DataReleaseError as error:
        reasons.add(error.code)
    if request.security_identity is not None:
        try:
            validate_original_filing_identity(
                request.security_identity,
                cik=original.source.cik,
                ticker=request.security_identity.security_id,
                accepted_at=original.source.available_at,
                facts=original.report.facts,
            )
        except IdentityResolutionError as error:
            reasons.add(error.code)
    return tuple(sorted(reasons))
