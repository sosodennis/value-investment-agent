"""Bootstrap source-bound mappings from validated originals in the service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field, model_validator

from .automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_policy_digest,
)
from .automatic_mapping_batch import (
    AutomaticMappingBatchDecisionV1,
    AutomaticMappingBatchRequestV1,
)
from .automatic_mapping_runner import (
    approve_mapping_batch,
    require_automatic_mapping_authority,
)
from .command_artifacts import EvidenceArtifactStore
from .contracts import InitialModelId, IssueV1, SecSourceRequestV1, Severity
from .data_releases import ArtifactRefV1, DataReleaseError, DataReleaseTrustRootsV1
from .facts import CanonicalMappingV1
from .ingestion_mapping import (
    IngestionMappingResolutionV1,
    IngestionMappingResolverPort,
    ValidatedOriginalV1,
)
from .policies import initial_model_specs
from .serialization import sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError
from .taxonomy_evidence import (
    TAXONOMY_CACHE_ARCHIVE_ROLE,
    build_taxonomy_cache_archive,
    taxonomy_cache_archive_digest,
)
from .valuation_requirements import automatic_source_requirements_profile


class AutomaticSecIngestionRequestV1(SecSourceRequestV1):
    protocol: Literal["automatic-sec-ingestion-v1"] = "automatic-sec-ingestion-v1"
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluator_id: str = Field(min_length=1, max_length=128)
    mapping_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_version: str = Field(min_length=1, max_length=128)
    model_id: InitialModelId
    model_version: str = Field(min_length=1, max_length=128)
    requirements_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def automatic_source_is_pinned(self) -> AutomaticSecIngestionRequestV1:
        profile = automatic_source_requirements_profile(
            self.model_id, self.requirements_digest
        )
        if (
            self.identity_basis != "original-filing-dei-v1"
            or self.filing.accession_number is None
            or self.filing.forms != ("10-K",)
            or self.supplemental_filing_policy != "sec-equity-award-proxy.v2"
        ):
            raise ValueError(
                "automatic mapping requires a pinned annual filing and award-source policy"
            )
        if (
            self.requirements_digest != profile.digest
            or set(self.required_fields) != set(profile.required_fact_fields)
            or not any(
                m.model_id == self.model_id and m.model_version == self.model_version
                for m in initial_model_specs()
            )
        ):
            raise ValueError(
                "automatic acquisition requires exact service model requirements"
            )
        return self


class MappingPublisherPort(Protocol):
    def publish_mapping(self, mapping: CanonicalMappingV1) -> None: ...


@dataclass(frozen=True)
class AutomaticSourceMappingAuthority:
    artifacts: EvidenceArtifactStore
    content: ContentAddressedStore
    metadata: MappingPublisherPort
    trust_roots: DataReleaseTrustRootsV1
    private_key: Ed25519PrivateKey
    source_revision: str
    taxonomy_cache_dir: Path
    taxonomy_cache_sha256: str

    def runtime_pin(self, request: AutomaticSecIngestionRequestV1) -> str:
        require_automatic_mapping_authority(
            request.evaluator_id,
            trust_roots=self.trust_roots,
            private_key=self.private_key,
        )
        if (
            request.source_revision != self.source_revision
            or request.mapping_policy_digest != automatic_mapping_policy_digest()
        ):
            raise DataReleaseError(
                "MAPPING_AUTOMATIC_RUNTIME_MISMATCH",
                "automatic source revision and policy must match the installed runtime",
            )
        return sha256_digest(
            {
                "source_revision": self.source_revision,
                "evaluator_id": request.evaluator_id,
                "evaluator": self.trust_roots.automatic_mapping_evaluators[
                    request.evaluator_id
                ],
                "taxonomy_cache_sha256": self.taxonomy_cache_sha256,
            }
        )

    def resolver_for(
        self, request: AutomaticSecIngestionRequestV1
    ) -> IngestionMappingResolverPort:
        self.runtime_pin(request)
        return _AutomaticSourceMappingResolver(self, request)

    def _retain_bytes(
        self, digest: str, *, media_type: str, role: str
    ) -> ArtifactRefV1:
        publication = self.artifacts.put_bytes_with_receipt(
            "automatic-source-bytes-" + digest,
            self.content.get(digest, media_type=media_type),
        )
        return ArtifactRefV1(
            artifact_id=publication.artifact.artifact_id,
            content_hash=publication.artifact.content_hash,
            media_type=publication.artifact.media_type,
            role=role,
        )

    def _taxonomy_ref(self, digest: str) -> ArtifactRefV1:
        # An existing manifest is sufficient; otherwise retain the exact cache tree.
        try:
            return self._retain_bytes(
                digest,
                media_type="application/octet-stream",
                role="sec-taxonomy-manifest-v1",
            )
        except SnapshotError as error:
            if error.code not in {"SOURCE_BYTES_UNAVAILABLE", "CONTENT_NOT_FOUND"}:
                raise
        artifact_id = "automatic-source-taxonomy-" + digest
        try:
            record = self.artifacts.get(artifact_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            archive = build_taxonomy_cache_archive(self.taxonomy_cache_dir)
            if taxonomy_cache_archive_digest(archive) != digest:
                raise DataReleaseError(
                    "MAPPING_AUTOMATIC_TAXONOMY_MISMATCH",
                    "installed taxonomy differs from the validated original",
                )
            record = self.artifacts.put_bytes_with_receipt(
                artifact_id, archive, media_type="application/zip"
            ).artifact
        else:
            if (
                taxonomy_cache_archive_digest(self.artifacts.read(artifact_id))
                != digest
            ):
                raise DataReleaseError(
                    "MAPPING_AUTOMATIC_TAXONOMY_MISMATCH",
                    "retained taxonomy differs from the validated original",
                )
        return ArtifactRefV1(
            artifact_id=record.artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role=TAXONOMY_CACHE_ARCHIVE_ROLE,
        )


@dataclass(frozen=True)
class _AutomaticSourceMappingResolver:
    authority: AutomaticSourceMappingAuthority
    request: AutomaticSecIngestionRequestV1

    def resolve(self, validated: ValidatedOriginalV1) -> IngestionMappingResolutionV1:
        authority, request = self.authority, self.request
        authority.runtime_pin(request)
        original, integrity = validated.original, validated.integrity
        if (
            validated.identity != request.identity
            or original.source.cik != request.cik
            or original.source.accession_number != request.filing.accession_number
            or original.decision_at != request.valuation_timestamp
            or original.report.taxonomy_cache_hash != authority.taxonomy_cache_sha256
        ):
            raise DataReleaseError(
                "MAPPING_AUTOMATIC_SOURCE_MISMATCH",
                "validated original differs from the pinned acquisition",
            )
        refs = []
        for source in validated.captured_sources:
            refs.append(
                authority._retain_bytes(
                    source.content_hash,
                    media_type=source.media_type,
                    role="sec-original-source-v1",
                )
            )
        for digest in sorted(
            {integrity.parser_input_hash, integrity.archive_member_hash}
        ):
            refs.append(
                authority._retain_bytes(
                    digest,
                    media_type=validated.primary_media_type,
                    role="sec-parser-input-v1",
                )
            )
        refs.append(authority._taxonomy_ref(original.report.taxonomy_cache_hash or ""))
        for role, value in (
            ("sec-original-issuer-evidence-v1", original),
            ("sec-issuer-integrity-v1", integrity),
        ):
            publication = authority.artifacts.put_with_receipt(
                role + "-" + sha256_digest(value), value
            )
            refs.append(
                ArtifactRefV1(
                    artifact_id=publication.artifact.artifact_id,
                    content_hash=publication.artifact.content_hash,
                    media_type=publication.artifact.media_type,
                    role=role,
                )
            )
        unique = {ref.artifact_id: ref for ref in refs}
        batch_request = AutomaticMappingBatchRequestV1(
            source_revision=request.source_revision,
            evaluator_id=request.evaluator_id,
            original=original,
            integrity=integrity,
            security_identity=validated.identity,
            evidence_refs=tuple(unique[key] for key in sorted(unique)),
            mapping_version=request.mapping_version,
            model_version=request.model_version,
            requirements=automatic_source_requirements_profile(
                request.model_id, request.requirements_digest
            ),
        )
        receipt = approve_mapping_batch(
            batch_request,
            artifacts=authority.artifacts,
            trust_roots=authority.trust_roots,
            private_key=authority.private_key,
        )
        raw = authority.artifacts.read(
            receipt.decision_publication.artifact.artifact_id
        )
        if hashlib.sha256(raw).hexdigest() != receipt.output_digest:
            raise DataReleaseError(
                "MAPPING_AUTOMATIC_DECISION_HASH_MISMATCH",
                "retained batch decision differs from its digest",
            )
        batch = AutomaticMappingBatchDecisionV1.model_validate_json(raw)
        mappings: list[CanonicalMappingV1] = []
        issues: list[IssueV1] = []
        missing: list[str] = []
        for role_decision in batch.roles:
            for outcome in role_decision.proposal_decisions():
                if outcome.status == "abstain":
                    missing.append(role_decision.normalized_field)
                    issues.extend(
                        IssueV1(
                            code=code,
                            field=role_decision.normalized_field,
                            severity=Severity.ERROR,
                            message="automatic source mapping abstained for this original",
                        )
                        for code in outcome.reason_codes
                    )
                    continue
                assert outcome.decision is not None
                raw = authority.artifacts.read(outcome.decision.artifact_id)
                if hashlib.sha256(raw).hexdigest() != outcome.decision.content_hash:
                    raise DataReleaseError(
                        "MAPPING_AUTOMATIC_DECISION_HASH_MISMATCH",
                        "retained role decision differs from its digest",
                    )
                decision = AutomaticMappingDecisionV1.model_validate_json(raw)
                assert decision.mapping is not None
                authority.metadata.publish_mapping(decision.mapping)
                mappings.append(decision.mapping)
        return IngestionMappingResolutionV1(
            mappings=tuple(mappings),
            evidence_ref=receipt.decision_publication.artifact.artifact_id,
            missing_fields=tuple(sorted(set(missing))),
            issues=tuple(issues),
        )
