"""Retained service-issued authority for one conditional terminal-growth edit."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from .artifact_evidence import EvidenceArtifactReader, read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .contracts import ConditionalRevisionRefV1, InitialModelId
from .data_releases import ArtifactRefV1, DataReleaseError
from .forward_evidence import (
    ForwardEvidenceClaimStatus,
    ForwardEvidenceMetric,
    ForwardEvidenceReviewRefV1,
    ForwardEvidenceReviewRequestV1,
    ForwardEvidenceReviewResponseV1,
    review_forward_evidence,
)
from .operations import guard_execution_deadline
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .valuation_preparation import (
    AutomaticValuationPreparationV1,
    ManualProvenanceV1,
    ManualValuationOverrideRequestV1,
    apply_conditional_terminal_growth_revision,
)

REVISION_PREFIX = "conditional-revision-v1-"
FORWARD_REVIEW_PREFIX = "forward-review-v1-"
REVISION_POLICY_VERSION: Final = "conditional-terminal-growth-revision-policy-v1"


class ConditionalRevisionError(ValueError):
    pass


class ConditionalRevisionForbidden(ConditionalRevisionError):
    pass


class RevisionActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)


class ConditionalRevisionSelectorV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    data_release_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: InitialModelId
    policy_id: str = Field(min_length=1)


class ConditionalRevisionProofV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conditional-terminal-growth-revision-v1"] = (
        "conditional-terminal-growth-revision-v1"
    )
    policy_version: Literal["conditional-terminal-growth-revision-policy-v1"] = (
        REVISION_POLICY_VERSION
    )
    actor: RevisionActor
    selector: ConditionalRevisionSelectorV1
    automatic_preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    automatic_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: ManualProvenanceV1
    terminal_growth: Decimal = Field(ge=0, le=Decimal("0.04"), allow_inf_nan=False)

    forward_review_ref: ForwardEvidenceReviewRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ForwardReviewWitnessV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["forward-evidence-review-witness-v1"] = (
        "forward-evidence-review-witness-v1"
    )
    actor: RevisionActor
    request: ForwardEvidenceReviewRequestV1
    review: ForwardEvidenceReviewResponseV1


def _forward_review_dependencies(witness: ForwardReviewWitnessV1) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                witness.request.automatic_preparation_digest,
                witness.review.reference_digest,
                *(claim.source.content_hash for claim in witness.request.claims),
            }
        )
    )


def retain_forward_review(
    artifacts: EvidenceArtifactStore,
    request: ForwardEvidenceReviewRequestV1,
    *,
    actor: RevisionActor,
    deadline_at: datetime | None,
) -> ForwardEvidenceReviewResponseV1:
    guard_execution_deadline(deadline_at)
    review = review_forward_evidence(request)
    if review.status != "prepared":
        return review
    witness = ForwardReviewWitnessV1(actor=actor, request=request, review=review)
    content_hash = sha256_digest(witness)
    ref = ForwardEvidenceReviewRefV1(
        artifact_id=f"{FORWARD_REVIEW_PREFIX}{content_hash}", content_hash=content_hash
    )
    dependencies = _forward_review_dependencies(witness)
    publication = artifacts.put_with_receipt(
        ref.artifact_id, witness, dependency_hashes=dependencies, retention="evidence"
    )
    record = publication.artifact
    if (
        record.artifact_id != ref.artifact_id
        or record.content_hash != ref.content_hash
        or record.media_type != ref.media_type
        or record.status != "valid"
        or record.retention != "evidence"
        or record.dependency_hashes != dependencies
    ):
        raise ConditionalRevisionError(
            "review publication did not retain exact evidence"
        )
    guard_execution_deadline(deadline_at)
    return review.model_copy(update={"review_ref": ref})


def read_forward_review(
    artifacts: EvidenceArtifactReader,
    ref: ForwardEvidenceReviewRefV1,
    *,
    actor: RevisionActor | None,
    deadline_at: datetime | None,
) -> ForwardReviewWitnessV1:
    if actor is None:
        raise ConditionalRevisionForbidden("review requires its authenticated owner")
    if ref.artifact_id != f"{FORWARD_REVIEW_PREFIX}{ref.content_hash}":
        raise ConditionalRevisionError("review reference is not content addressed")
    guard_execution_deadline(deadline_at)
    try:
        raw = read_retained_artifact(
            artifacts,
            ArtifactRefV1(
                artifact_id=ref.artifact_id,
                content_hash=ref.content_hash,
                media_type=ref.media_type,
                role="forward_evidence_review",
            ),
        )
        if sha256(raw).hexdigest() != ref.content_hash:
            raise ConditionalRevisionError("review bytes do not match their reference")
        witness = ForwardReviewWitnessV1.model_validate_json(raw)
        if canonical_bytes(witness) != raw:
            raise ConditionalRevisionError("review bytes are not canonical")
    except (SnapshotError, DataReleaseError, ValueError) as error:
        raise ConditionalRevisionError(
            "retained review evidence is unavailable or invalid"
        ) from error
    if witness.actor != actor:
        raise ConditionalRevisionForbidden("review requires its authenticated owner")
    if (
        witness.review.review_ref is not None
        or witness.review.status != "prepared"
        or canonical_bytes(review_forward_evidence(witness.request))
        != canonical_bytes(witness.review)
    ):
        raise ConditionalRevisionError("retained review did not reproduce")
    record = artifacts.get(ref.artifact_id)
    if (
        record.dependency_hashes != _forward_review_dependencies(witness)
        or record.status != "valid"
        or record.retention != "evidence"
        or record.content_hash != ref.content_hash
        or record.media_type != ref.media_type
    ):
        raise ConditionalRevisionError("review dependencies are not retained")
    guard_execution_deadline(deadline_at)
    return witness


def validate_revision_forward_review(
    artifacts: EvidenceArtifactReader,
    automatic: AutomaticValuationPreparationV1,
    proof: ConditionalRevisionProofV1,
    *,
    actor: RevisionActor | None,
    deadline_at: datetime | None,
) -> None:
    citation = proof.provenance.forward_reference
    ref = proof.forward_review_ref
    if citation is None and ref is None:
        return
    if citation is None or ref is None or automatic.input is None:
        raise ConditionalRevisionError(
            "researched revision requires its retained review and citation"
        )
    witness = read_forward_review(artifacts, ref, actor=actor, deadline_at=deadline_at)
    request = witness.request
    original = automatic.input
    if (
        request.automatic_preparation_digest != automatic.preparation_digest
        or request.issuer_id != original.identity.issuer_id
        or request.ticker != original.identity.security_id
        or request.model_id != automatic.model_id
        or request.assumption_path != "assumptions.terminal_growth"
        or request.valuation_timestamp != original.valuation_context.valuation_timestamp
    ):
        raise ConditionalRevisionError(
            "review is bound to another automatic preparation"
        )
    selected = tuple(
        claim for claim in witness.review.claims if claim.claim_id == citation.claim_id
    )
    if len(selected) != 1:
        raise ConditionalRevisionError("review requires one selected claim")
    claim = selected[0]
    if (
        claim.status is not ForwardEvidenceClaimStatus.ACCEPTED
        or claim.claim_id not in witness.review.accepted_claim_ids
        or claim.metric is not ForwardEvidenceMetric.TERMINAL_GROWTH
        or claim.unit != "ratio"
        or claim.value != proof.terminal_growth
        or claim.assumption_path != request.assumption_path
        or claim.issuer_id != original.identity.issuer_id
        or claim.ticker != original.identity.security_id
        or claim.model_id != automatic.model_id
        or citation.source_url != claim.source.source_url
        or citation.source_content_hash != claim.source.content_hash
        or citation.citation != claim.source.retained_passage
        or citation.license_reference != claim.source.license_reference
    ):
        raise ConditionalRevisionError(
            "revision does not match the reviewed terminal claim"
        )


def revision_selector(
    automatic: AutomaticValuationPreparationV1,
) -> ConditionalRevisionSelectorV1:
    if (
        automatic.input is None
        or automatic.input.valuation_context.data_release_manifest_digest is None
    ):
        raise ConditionalRevisionError("revision requires a pinned prepared input")
    return ConditionalRevisionSelectorV1(
        snapshot_id=automatic.input.valuation_context.data_snapshot_id,
        data_release_manifest_digest=automatic.input.valuation_context.data_release_manifest_digest,
        model_id=automatic.model_id,
        policy_id=automatic.policy_id,
    )


def bind_revision(
    automatic: AutomaticValuationPreparationV1,
    proof: ConditionalRevisionProofV1,
    ref: ConditionalRevisionRefV1,
) -> AutomaticValuationPreparationV1:
    if (
        automatic.input is None
        or proof.selector != revision_selector(automatic)
        or proof.automatic_preparation_digest != automatic.preparation_digest
        or proof.automatic_input_digest != automatic.input.input_digest
        or proof.provenance.author != proof.actor.subject_id
        or proof.provenance.automatic_preparation_digest != automatic.preparation_digest
    ):
        raise ConditionalRevisionError(
            "revision does not match the automatic preparation"
        )
    revised = apply_conditional_terminal_growth_revision(
        automatic, value=proof.terminal_growth, provenance=proof.provenance
    )
    assert revised.input is not None
    value = revised.input.model_copy(
        update={
            "provenance": revised.input.provenance.model_copy(
                update={"conditional_revision_ref": ref}
            ),
        }
    ).with_digest()
    payload = revised.model_dump(exclude={"preparation_digest"})
    payload["input"] = value
    return AutomaticValuationPreparationV1.model_validate(
        {
            **payload,
            "preparation_digest": sha256_digest(
                {
                    **payload,
                    "automatic_preparation_digest": automatic.preparation_digest,
                }
            ),
        }
    )


def issue_revision(
    artifacts: EvidenceArtifactStore,
    automatic: AutomaticValuationPreparationV1,
    request: ManualValuationOverrideRequestV1,
    *,
    actor: RevisionActor,
    dependency_hashes: tuple[str, ...],
    deadline_at: datetime | None,
) -> AutomaticValuationPreparationV1:
    if request.path != "assumptions.terminal_growth":
        raise ConditionalRevisionError(
            "conditional revision supports only terminal growth"
        )
    if canonical_bytes(request.preparation) != canonical_bytes(automatic):
        raise ConditionalRevisionError(
            "revision requires the exact automatic preparation"
        )
    assert automatic.input is not None and automatic.input.input_digest is not None
    provenance = request.provenance.model_copy(update={"author": actor.subject_id})
    proof = ConditionalRevisionProofV1(
        actor=actor,
        selector=revision_selector(automatic),
        automatic_preparation_digest=automatic.preparation_digest,
        automatic_input_digest=automatic.input.input_digest,
        provenance=provenance,
        terminal_growth=request.value,
        forward_review_ref=request.forward_review_ref,
    )
    content_hash = sha256_digest(proof)
    ref = ConditionalRevisionRefV1(
        artifact_id=f"{REVISION_PREFIX}{content_hash}", content_hash=content_hash
    )
    validate_revision_forward_review(
        artifacts, automatic, proof, actor=actor, deadline_at=deadline_at
    )
    revised = bind_revision(automatic, proof, ref)
    dependency_hashes = tuple(
        sorted(
            {
                *dependency_hashes,
                *(
                    (proof.forward_review_ref.content_hash,)
                    if proof.forward_review_ref is not None
                    else ()
                ),
            }
        )
    )
    guard_execution_deadline(deadline_at)
    publication = artifacts.put_with_receipt(
        ref.artifact_id,
        proof,
        dependency_hashes=dependency_hashes,
        retention="evidence",
    )
    if (
        publication.artifact.content_hash != ref.content_hash
        or publication.artifact.artifact_id != ref.artifact_id
        or publication.artifact.status != "valid"
        or publication.artifact.retention != "evidence"
        or publication.artifact.media_type != ref.media_type
        or publication.artifact.dependency_hashes != dependency_hashes
    ):
        raise ConditionalRevisionError(
            "revision publication did not retain exact evidence"
        )
    guard_execution_deadline(deadline_at)
    return revised


def read_revision(
    artifacts: EvidenceArtifactReader,
    ref: ConditionalRevisionRefV1,
    *,
    actor: RevisionActor | None,
    deadline_at: datetime | None,
) -> ConditionalRevisionProofV1:
    if actor is None:
        raise ConditionalRevisionForbidden("revision requires its authenticated owner")
    if ref.artifact_id != f"{REVISION_PREFIX}{ref.content_hash}":
        raise ConditionalRevisionError("revision reference is not content addressed")
    guard_execution_deadline(deadline_at)
    try:
        raw = read_retained_artifact(
            artifacts,
            ArtifactRefV1(
                artifact_id=ref.artifact_id,
                content_hash=ref.content_hash,
                media_type=ref.media_type,
                role="conditional_revision",
            ),
        )
        if sha256(raw).hexdigest() != ref.content_hash:
            raise ConditionalRevisionError(
                "revision bytes do not match their reference"
            )
        proof = ConditionalRevisionProofV1.model_validate_json(raw)
        if canonical_bytes(proof) != raw:
            raise ConditionalRevisionError("revision bytes are not canonical")
    except (SnapshotError, DataReleaseError, ValueError) as error:
        raise ConditionalRevisionError(
            "retained revision evidence is unavailable or invalid"
        ) from error
    if proof.actor != actor:
        raise ConditionalRevisionForbidden("revision requires its authenticated owner")
    guard_execution_deadline(deadline_at)
    return proof
