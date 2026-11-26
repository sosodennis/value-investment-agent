from __future__ import annotations

from collections.abc import Callable

import hashlib

from .data_releases import ArtifactRefV1, DataReleaseTrustRootsV1
from .fiscal_candidate_contracts import FiscalStatementCandidateV2
from .fiscal_display_contracts import SignedFiscalDisplayDecisionV1
from .fiscal_release_contracts import (
    FiscalReleaseCanaryV1,
    FiscalReleaseChecksV1,
    FiscalReleaseEnvelopeV1,
    FiscalReleaseManifestV1,
    FiscalStoredVerificationV1,
    fiscal_manifest,
)
from .publication_codec import verify_publication_pair
from .serialization import canonical_bytes, sha256_digest


def verify_retained_fiscal_publication(
    manifest: FiscalReleaseManifestV1,
    verification: FiscalStoredVerificationV1,
    roots: DataReleaseTrustRootsV1,
    read: Callable[[ArtifactRefV1], bytes],
) -> None:
    verify_publication_pair(manifest, verification, roots)
    envelope_raw = read(manifest.envelope_ref)
    envelope = FiscalReleaseEnvelopeV1.model_validate_json(envelope_raw)
    checks_raw = read(verification.signed.checked_ref)
    checks = FiscalReleaseChecksV1.model_validate_json(checks_raw)
    report_raw = read(verification.canary_ref)
    report = FiscalReleaseCanaryV1.model_validate_json(report_raw)
    if (
        canonical_bytes(envelope) != envelope_raw
        or envelope.artifact_id != manifest.envelope_ref.artifact_id
        or canonical_bytes(checks) != checks_raw
        or checks.artifact_id != verification.signed.checked_ref.artifact_id
        or checks.manifest_digest != manifest.manifest_digest
        or checks.candidate_content_digest != envelope.candidate_content_digest
        or canonical_bytes(report) != report_raw
        or report.artifact_id != verification.canary_ref.artifact_id
        or report.manifest_digest != manifest.manifest_digest
        or report.verification_digest != verification.verification_digest
        or report.checked_ref != verification.signed.checked_ref
    ):
        raise ValueError("retained fiscal publication evidence differs")
    for reference in (
        envelope.approved.candidate_ref,
        envelope.approved.decision_ref,
        envelope.projection_ref,
        *checks.retained_refs,
    ):
        read(reference)

    candidate = FiscalStatementCandidateV2.model_validate_json(
        read(envelope.approved.candidate_ref)
    )
    decision = SignedFiscalDisplayDecisionV1.model_validate_json(
        read(envelope.approved.decision_ref)
    )
    content = candidate.body.content
    if (
        decision.body.command.request.candidate_ref != envelope.approved.candidate_ref
        or decision.body.review.reviewed.content != content
        or envelope.candidate_content_digest != content.content_digest
        or envelope.projection_ref != content.projection_ref
    ):
        raise ValueError(
            "retained fiscal candidate, display decision or projection binding differs"
        )
    expected = fiscal_manifest(
        envelope,
        manifest.envelope_ref,
        scope=content.scope,
        cutoff_at=content.cutoff_at,
        display_profile_digest=content.source_uses[0].scope.display_profile_digest,
        created_at=decision.body.signed_at,
    )
    if manifest != expected:
        raise ValueError(
            "retained fiscal release identity differs from its owning inputs"
        )
    signed_ref = ArtifactRefV1(
        role="fiscal-release-signed-v1",
        artifact_id="fiscal-release-signed-v1:" + manifest.manifest_digest,
        content_hash=sha256_digest(verification.signed),
        media_type="application/json",
    )
    marker_bytes = verification.signed.signing_bytes()
    marker_ref = ArtifactRefV1(
        role="fiscal-release-signing-v1",
        artifact_id="fiscal-release-signing-v1:" + manifest.manifest_digest,
        content_hash=hashlib.sha256(marker_bytes).hexdigest(),
        media_type="application/json",
    )
    if (
        read(signed_ref) != canonical_bytes(verification.signed)
        or read(marker_ref) != marker_bytes
    ):
        raise ValueError("retained fiscal signing outcome or frozen preimage differs")
