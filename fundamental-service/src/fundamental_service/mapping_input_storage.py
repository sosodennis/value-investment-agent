"""Versioned mapping inputs referencing a shared immutable original report."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field, JsonValue, model_validator

from .contracts import SecIntegrityEvidenceV1
from .data_releases import ArtifactRefV1, DataReleaseError, ReleaseModel
from .original_issuer import (
    OriginalIssuerEvidenceChecks,
    OriginalIssuerEvidenceV1,
    OriginalOperatingSourceV1,
)
from .mapping_input_identity import MappingInputDigests
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes
from .snapshots import SnapshotError

if TYPE_CHECKING:
    from .command_artifacts import EvidenceArtifactStore


PROTOCOL: Final = "fundamental.mapping-input-artifact.v2"
ORIGINAL_ROLE = "automatic-mapping-parser-report-v1"
ModelT = TypeVar("ModelT", bound=BaseModel)


class MappingInputReader(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...


class StoredMappingInputV2(ReleaseModel):
    protocol: Literal["fundamental.mapping-input-artifact.v2"] = PROTOCOL
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_ref: ArtifactRefV1
    original: dict[str, JsonValue]
    request: dict[str, JsonValue]

    @model_validator(mode="after")
    def original_is_referenced(self) -> StoredMappingInputV2:
        if (
            "original" in self.request
            or "report" in self.original
            or self.original_ref.role != ORIGINAL_ROLE
            or self.original_ref.media_type != "application/json"
        ):
            raise ValueError(
                "mapping originals require one exact JSON artifact reference"
            )
        return self


def mapping_input_report_dependency(
    raw: bytes,
) -> tuple[ArtifactRefV1, tuple[str, ...]] | None:
    """Expose the v2 reference and dependencies without re-evaluating mappings.

    The caller must authenticate the input bytes against its release reference.
    Legacy embedded reports have no separate artifact to recheck.
    """
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
        return None
    envelope = StoredMappingInputV2.model_validate_json(raw)
    source = OriginalOperatingSourceV1.model_validate_json(
        canonical_bytes(envelope.original["source"])
    )
    integrity = SecIntegrityEvidenceV1.model_validate_json(
        canonical_bytes(envelope.request["integrity"])
    )
    if source.parser_input_hash != integrity.parser_input_hash:
        raise DataReleaseError(
            "MAPPING_ORIGINAL_ARTIFACT_MISMATCH",
            "shared mapping report source dependencies differ",
        )
    return envelope.original_ref, tuple(
        sorted({source.parser_input_hash, integrity.taxonomy_manifest_hash})
    )


def require_mapping_report_record(
    record: ArtifactRecordV1,
    ref: ArtifactRefV1,
    expected_dependencies: tuple[str, ...],
) -> None:
    """Check the exact retained report identity and its source dependencies."""
    if (
        record.artifact_id != ref.artifact_id
        or record.status != "valid"
        or record.retention != "evidence"
        or record.media_type != ref.media_type
        or record.content_hash != ref.content_hash
        or record.dependency_hashes != expected_dependencies
    ):
        raise DataReleaseError(
            "MAPPING_ORIGINAL_ARTIFACT_MISMATCH",
            "shared mapping report requires valid retained evidence and exact dependencies",
        )


def publish_mapping_input(
    request: BaseModel,
    original: OriginalIssuerEvidenceV1,
    *,
    artifacts: EvidenceArtifactStore,
    evidence_refs: tuple[ArtifactRefV1, ...],
    batch: bool = False,
    input_digests: MappingInputDigests | None = None,
) -> tuple[ArtifactPublicationV1, ArtifactPublicationV1]:
    """Return report and envelope publications, preserving both write receipts."""
    identities = input_digests or MappingInputDigests()
    report = identities.report_bytes(original.report)
    report_digest = identities.report_content_digest(original.report)
    dependencies = {ref.content_hash for ref in evidence_refs}
    publication = artifacts.put_bytes_with_receipt(
        "automatic-mapping-parser-report-" + report_digest,
        report,
        media_type="application/json",
        dependency_hashes=tuple(
            sorted(
                value
                for value in {
                    original.report.source_content_hash,
                    original.report.taxonomy_cache_hash,
                }
                if value
            )
        ),
    )
    envelope = StoredMappingInputV2(
        input_digest=identities.input_digest(request),
        original_ref=ArtifactRefV1(
            artifact_id=publication.artifact.artifact_id,
            content_hash=publication.artifact.content_hash,
            media_type=publication.artifact.media_type,
            role=ORIGINAL_ROLE,
        ),
        original=original.model_dump(mode="json", exclude={"report"}),
        request=request.model_dump(mode="json", exclude={"original"}),
    )
    input_publication = artifacts.put_with_receipt(
        mapping_input_id(envelope.input_digest, batch=batch),
        envelope,
        dependency_hashes=tuple(
            sorted(dependencies | {report_digest, original.source.content_hash})
        ),
    )
    return publication, input_publication


def mapping_input_id(input_digest: str, *, batch: bool = False) -> str:
    prefix = "automatic-mapping-batch-input-" if batch else "automatic-mapping-input-"
    return prefix + "v2-" + input_digest


def resolve_mapping_input(
    raw: bytes,
    model: type[ModelT],
    *,
    artifacts: MappingInputReader,
    original_checks: OriginalIssuerEvidenceChecks | None = None,
    input_digests: MappingInputDigests | None = None,
) -> ModelT:
    """Read explicitly retained v1 inputs or resolve and validate a v2 envelope."""
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
        return model.model_validate_json(raw, context=original_checks)
    envelope = StoredMappingInputV2.model_validate_json(raw)
    ref = envelope.original_ref
    original_raw = artifacts.read(ref.artifact_id)
    if hashlib.sha256(original_raw).hexdigest() != ref.content_hash:
        raise DataReleaseError(
            "MAPPING_ORIGINAL_HASH_MISMATCH", "shared mapping original changed"
        )
    resolution = (original_checks or OriginalIssuerEvidenceChecks()).resolve_report(
        original_raw
    )
    report = resolution.report
    record = artifacts.get(ref.artifact_id)
    expected_dependencies = tuple(
        sorted(
            value
            for value in {
                report.source_content_hash,
                report.taxonomy_cache_hash,
            }
            if value
        )
    )
    require_mapping_report_record(record, ref, expected_dependencies)
    request = model.model_validate_json(
        canonical_bytes(
            {
                **envelope.request,
                "original": {
                    **envelope.original,
                    "report": None,
                },
            }
        ),
        context=resolution,
    )
    if (input_digests or MappingInputDigests()).input_digest(
        request
    ) != envelope.input_digest:
        raise DataReleaseError(
            "MAPPING_INPUT_IDENTITY_MISMATCH",
            "resolved mapping input differs from its retained semantic identity",
        )
    return request


def read_mapping_batch_input(
    input_digest: str,
    model: type[ModelT],
    *,
    artifacts: EvidenceArtifactStore,
    original_checks: OriginalIssuerEvidenceChecks | None = None,
    input_digests: MappingInputDigests | None = None,
) -> tuple[ArtifactRefV1, ModelT]:
    """Prefer the new envelope; only an absent envelope permits a retained v1 read."""
    artifact_id = mapping_input_id(input_digest, batch=True)
    try:
        record = artifacts.get(artifact_id)
    except SnapshotError as error:
        if error.code != "ARTIFACT_NOT_FOUND":
            raise
        artifact_id = "automatic-mapping-batch-input-" + input_digest
        record = artifacts.get(artifact_id)
    raw = artifacts.read(artifact_id)
    if (
        record.status != "valid"
        or record.retention != "evidence"
        or record.media_type != "application/json"
        or hashlib.sha256(raw).hexdigest() != record.content_hash
    ):
        raise DataReleaseError(
            "MAPPING_INPUT_ARTIFACT_MISMATCH",
            "mapping input requires exact retained JSON evidence",
        )
    identities = input_digests or MappingInputDigests()
    request = resolve_mapping_input(
        raw,
        model,
        artifacts=artifacts,
        original_checks=original_checks,
        input_digests=identities,
    )
    if identities.input_digest(request) != input_digest:
        raise DataReleaseError(
            "MAPPING_INPUT_IDENTITY_MISMATCH", "mapping batch input identity differs"
        )
    return (
        ArtifactRefV1(
            artifact_id=artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role="automatic-mapping-batch-input-v1",
        ),
        request,
    )
