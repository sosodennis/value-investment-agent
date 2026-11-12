"""One-shot source preparation outside the serving API request path."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Generic, Literal, Protocol, TypeAlias, TypeVar

from pydantic import Field, TypeAdapter, model_validator

from .automatic_mapping import AutomaticMappingDecisionV1
from .automatic_mapping_batch import (
    AutomaticMappingBatchDecisionV1,
    AutomaticMappingBatchRequestV1,
)
from .automatic_source_mapping import (
    AutomaticSecIngestionRequestV1,
    AutomaticSourceMappingAuthority,
)

from .application import FundamentalApplication
from .contracts import (
    CallerApprovalEnvelopeV1,
    InitialModelId,
    QualityStatus,
    SecIngestionRequestV1,
    SecMappingReferenceV1,
    SecSourceRequestV1,
    SnapshotResolutionRequestV1,
    SnapshotResolutionV1,
    SourceRole,
    SourceSnapshotV1,
    StrictModel,
    ValuationEvidenceReadRequestV1,
)
from .data_releases import (
    ArtifactRefV1,
    DataReleaseActivationRequestV1,
    DataReleaseCandidatePublishRequestV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
)
from .facts import CanonicalMappingV1, canonical_fact_digest
from .operations import ServiceError, guard_caller_approval
from .history_composition import compose_original_history
from .release_runner import DataReleaseCanaryRunner
from .replay import ArtifactPublicationV1
from .uncertainty import UncertaintyReportV1
from .serialization import canonical_bytes, sha256_digest
from .source_acquisition import SecAcquisitionUseCase
from .snapshots import SnapshotError
from .valuation_preparation import AutomaticValuationPreparationV1
from .valuation_requirements import valuation_requirements_profile


SourceRequestT = TypeVar("SourceRequestT", bound=SecSourceRequestV1)


class _SourcePreparationPlan(StrictModel, Generic[SourceRequestT]):
    """Common issuer, chronology and runtime constraints for source plans."""

    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_profile_id: str = Field(min_length=1)
    model_id: InitialModelId
    ingestions: tuple[SourceRequestT, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def requirements_match(self) -> _SourcePreparationPlan[SourceRequestT]:
        profile = valuation_requirements_profile(self.model_id)
        required = set(profile.required_fact_fields)
        requested = {
            field for request in self.ingestions for field in request.required_fields
        }
        if not required <= requested <= required | set(profile.supporting_fact_fields):
            raise ValueError("source plan must cover the complete model requirements")
        first = self.ingestions[0]
        for request in self.ingestions:
            if any(
                getattr(request, field) != getattr(first, field)
                for field in (
                    "identity",
                    "cik",
                    "ticker",
                    "identity_basis",
                    "valuation_timestamp",
                    "fiscal_period_selector",
                    "coverage_profile",
                    "source_selection_policy",
                    "legal_use_profile",
                    "parser_version",
                    "policy_version",
                    "taxonomy_manifest_id",
                    "taxonomy_version",
                    "validation_profile_id",
                )
            ):
                raise ValueError(
                    "source plan components must share issuer, date and runtime profile"
                )
        if len(self.ingestions) > 1:
            accessions = tuple(
                request.filing.accession_number for request in self.ingestions
            )
            if (
                None in accessions
                or len(set(accessions)) != len(accessions)
                or any(request.filing.forms != ("10-K",) for request in self.ingestions)
            ):
                raise ValueError(
                    "history plan requires distinct pinned original annual filings"
                )
            if accessions != tuple(
                sorted(accession for accession in accessions if accession is not None)
            ):
                raise ValueError("history plan accessions must be sorted")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    def resolution_request(self) -> SnapshotResolutionRequestV1:
        first = self.ingestions[0]
        return SnapshotResolutionRequestV1(
            contract_version="fundamental.v1",
            release_profile_id=self.release_profile_id,
            identity=first.identity,
            valuation_timestamp=first.valuation_timestamp,
            source_selection_policy="pit-v1",
            coverage_profile=first.coverage_profile,
            required_fields=valuation_requirements_profile(
                self.model_id
            ).required_fact_fields,
        )


class SourcePreparationPlanV2(_SourcePreparationPlan[SecIngestionRequestV1]):
    """Explicit deployment input with pre-existing mapping decisions."""

    protocol: Literal["source-preparation-v2"] = "source-preparation-v2"

    @model_validator(mode="after")
    def mapping_references_match(self) -> SourcePreparationPlanV2:
        references: dict[str, SecMappingReferenceV1] = {}
        for request in self.ingestions:
            for reference in request.mappings:
                previous = references.setdefault(reference.decision_id, reference)
                if previous != reference:
                    raise ValueError("source plan mapping references must be coherent")
        return self


class AutomaticSourcePreparationPlanV1(
    _SourcePreparationPlan[AutomaticSecIngestionRequestV1]
):
    protocol: Literal["automatic-source-preparation-v1"] = (
        "automatic-source-preparation-v1"
    )

    @model_validator(mode="after")
    def automatic_pins_match(self) -> AutomaticSourcePreparationPlanV1:
        first = self.ingestions[0]
        for request in self.ingestions:
            if (
                request.source_revision != self.source_revision
                or request.model_id != self.model_id
                or any(
                    getattr(request, field) != getattr(first, field)
                    for field in (
                        "evaluator_id",
                        "mapping_policy_digest",
                        "mapping_version",
                        "model_version",
                        "requirements_digest",
                    )
                )
            ):
                raise ValueError(
                    "automatic source plan must pin one model, authority and policy"
                )
        return self


SourcePreparationPlan: TypeAlias = Annotated[
    SourcePreparationPlanV2 | AutomaticSourcePreparationPlanV1,
    Field(discriminator="protocol"),
]
SOURCE_PREPARATION_PLAN = TypeAdapter(SourcePreparationPlan)


class SourceAcquisitionOutcomeV1(StrictModel):
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accession_number: str | None = None
    quality_status: QualityStatus | None
    snapshot_id: str | None = None
    manifest_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    mapping_evidence_ref: ArtifactRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> SourceAcquisitionOutcomeV1:
        if (self.snapshot_id is None) != (self.manifest_digest is None):
            raise ValueError("acquisition snapshot identity and digest must be paired")
        if self.quality_status is None and (
            not self.issue_codes or self.snapshot_id is not None
        ):
            raise ValueError("failed acquisition requires issues without a snapshot")
        if self.quality_status is QualityStatus.VERIFIED and self.snapshot_id is None:
            raise ValueError("verified acquisition requires a stored snapshot")
        for values in (self.issue_codes, self.missing_evidence):
            if values != tuple(sorted(set(values))):
                raise ValueError("acquisition diagnostics must be canonical")
        return self


class SourcePreparationEvidenceV1(StrictModel):
    protocol: Literal["source-preparation-v1"] = "source-preparation-v1"
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_plan_ref: ArtifactRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    status: Literal["approval_required", "blocked", "calculated", "release_required"]
    snapshot_id: str | None = None
    snapshot_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    data_release_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    issue_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    source_outcomes: tuple[SourceAcquisitionOutcomeV1, ...] = Field(
        default=(), max_length=6, exclude_if=lambda value: not value
    )
    preparation: AutomaticValuationPreparationV1 | None = None
    calculation: UncertaintyReportV1 | None = None

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> SourcePreparationEvidenceV1:
        if self.source_plan_ref is not None and (
            self.source_plan_ref.content_hash != self.plan_digest
            or self.source_plan_ref.media_type != "application/json"
            or self.source_plan_ref.role
            not in {"source-preparation-plan-v2", "automatic-source-preparation-v1"}
        ):
            raise ValueError("source plan reference must bind the canonical input")
        if len({outcome.request_digest for outcome in self.source_outcomes}) != len(
            self.source_outcomes
        ):
            raise ValueError("source outcomes must retain distinct requests")
        if self.status != "blocked" and any(
            outcome.quality_status is not QualityStatus.VERIFIED
            for outcome in self.source_outcomes
        ):
            raise ValueError("incomplete acquisitions require a blocked outcome")
        if (self.snapshot_id is None) != (self.snapshot_manifest_digest is None):
            raise ValueError("snapshot identity and digest must be paired")
        if self.preparation is not None and (
            self.snapshot_id is None or self.data_release_manifest_digest is None
        ):
            raise ValueError("preparation must retain its snapshot and release")
        if self.status == "release_required" and (
            self.snapshot_id is None or self.preparation is not None
        ):
            raise ValueError("release_required must retain the unreleased snapshot")
        if (self.status == "calculated") != (self.calculation is not None):
            raise ValueError("calculated status must match calculation evidence")
        if self.status in {"approval_required", "calculated"} and (
            self.preparation is None or self.preparation.status != "prepared"
        ):
            raise ValueError("calculation flow requires a prepared valuation")
        return self


class PreparationArtifactWriter(Protocol):
    def put_with_receipt(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
    ) -> ArtifactPublicationV1: ...


class PreparationMetadataReader(Protocol):
    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1: ...

    def get_data_release_manifest(
        self, manifest_digest: str
    ) -> DataReleaseManifestV1 | None: ...


_EVIDENCE_MISS_CODES = frozenset(
    {
        "DATA_RELEASE_NOT_ACTIVE",
        "DATA_RELEASE_FIELDS_UNAVAILABLE",
        "SNAPSHOT_NOT_FOUND",
    }
)


class SourcePreparationRunner:
    def __init__(
        self,
        *,
        application: FundamentalApplication,
        metadata: PreparationMetadataReader,
        acquisition: SecAcquisitionUseCase | None,
        artifacts: PreparationArtifactWriter,
        canary: DataReleaseCanaryRunner | None,
    ) -> None:
        self._application = application
        self._metadata = metadata
        self._acquisition = acquisition
        self._artifacts = artifacts
        self._canary = canary

    def _plan_mappings(
        self, plan: SourcePreparationPlan
    ) -> tuple[tuple[SecMappingReferenceV1, ...], ...] | None:
        if isinstance(plan, SourcePreparationPlanV2):
            return tuple(request.mappings for request in plan.ingestions)
        if self._acquisition is None:
            return None
        groups = []
        for request in plan.ingestions:
            retained = self._acquisition.retained_acquisition(request)
            if (
                retained is None
                or retained.quality_status is not QualityStatus.VERIFIED
                or retained.mapping_evidence_ref is None
            ):
                return None
            artifacts = self._application.artifact_store
            record = artifacts.get(retained.mapping_evidence_ref)
            if record.status != "valid" or record.retention != "evidence":
                raise ValueError(
                    "automatic preparation requires valid retained mapping evidence"
                )
            batch = AutomaticMappingBatchDecisionV1.model_validate_json(
                artifacts.read(record.artifact_id)
            )
            batch_input = AutomaticMappingBatchRequestV1.model_validate_json(
                artifacts.read("automatic-mapping-batch-input-" + batch.input_digest)
            )
            if (
                sha256_digest(batch_input) != batch.input_digest
                or batch_input.original.source.cik != request.cik
                or batch_input.original.source.accession_number
                != request.filing.accession_number
                or batch_input.original.decision_at != request.valuation_timestamp
                or batch_input.security_identity != request.identity
                or batch_input.evaluator_id != request.evaluator_id
                or batch_input.mapping_version != request.mapping_version
                or batch_input.source_revision != batch.source_revision
                or batch_input.model_version != batch.model_version
                or batch_input.requirements != batch.requirements
                or batch.source_revision != request.source_revision
                or batch.policy_digest != request.mapping_policy_digest
                or batch.model_version != request.model_version
                or batch.requirements.digest != request.requirements_digest
            ):
                raise ValueError(
                    "retained automatic batch differs from source plan pins"
                )
            references = []
            for role in batch.roles:
                if role.status != "approved":
                    if role.normalized_field in request.required_fields:
                        return None
                    continue
                assert role.decision is not None
                decision = AutomaticMappingDecisionV1.model_validate_json(
                    artifacts.read(role.decision.artifact_id)
                )
                if (
                    sha256_digest(decision) != role.decision.content_hash
                    or decision.mapping is None
                    or decision.source_revision != request.source_revision
                    or decision.evaluator_id != request.evaluator_id
                    or decision.policy_digest != request.mapping_policy_digest
                    or decision.mapping.mapping_version != request.mapping_version
                    or decision.mapping.normalized_field != role.normalized_field
                ):
                    raise ValueError(
                        "automatic mapping decision differs from its retained reference"
                    )
                mapping = decision.mapping
                references.append(
                    SecMappingReferenceV1(
                        decision_id=mapping.decision_id,
                        mapping_version=mapping.mapping_version,
                        normalized_field=mapping.normalized_field,
                    )
                )
            groups.append(tuple(references))
        return tuple(groups)

    def _resolve(self, plan: SourcePreparationPlan) -> SnapshotResolutionV1 | None:
        try:
            resolution = self._application.resolve_snapshot(plan.resolution_request())
        except ServiceError as error:
            if error.code not in _EVIDENCE_MISS_CODES:
                raise
            return None
        snapshot = self._application.snapshot(resolution.snapshot_id)
        if not self._matches_plan(plan, snapshot):
            return None
        if resolution.data_release_manifest_digest is None:
            raise ValueError("preparation requires an immutable data release")
        manifest = self._metadata.get_data_release_manifest(
            resolution.data_release_manifest_digest
        )
        if manifest is None or manifest.manifest_digest != (
            resolution.data_release_manifest_digest
        ):
            raise ServiceError(
                "DATA_RELEASE_MANIFEST_MISMATCH",
                "resolved release manifest is unavailable or changed",
                status_code=409,
                retryable=False,
            )
        return resolution if self._matches_release(plan, snapshot, manifest) else None

    def _matches_release_mappings(
        self, plan: SourcePreparationPlan, manifest: DataReleaseManifestV1
    ) -> bool:
        released = {
            item.mapping_id: item.mapping_digest for item in manifest.mapping_refs
        }
        groups = self._plan_mappings(plan)
        if groups is None:
            return False
        references = {item.decision_id: item for group in groups for item in group}
        if not references.keys() <= released.keys():
            return False
        for key, reference in sorted(references.items()):
            mapping = self._metadata.get_mapping(key)
            if mapping.decision_id != key or sha256_digest(mapping) != released[key]:
                raise ServiceError(
                    "DATA_RELEASE_MAPPING_MISMATCH",
                    "plan mapping differs from the immutable release",
                    status_code=409,
                    retryable=False,
                )
            if (
                mapping.mapping_version != reference.mapping_version
                or mapping.normalized_field != reference.normalized_field
            ):
                return False
        return True

    def _matches_release(
        self,
        plan: SourcePreparationPlan,
        snapshot: SourceSnapshotV1,
        manifest: DataReleaseManifestV1,
    ) -> bool:
        if not self._matches_release_mappings(plan, manifest):
            return False
        declared = next(
            (
                item
                for item in manifest.snapshot_refs
                if item.snapshot_id == snapshot.snapshot_id
            ),
            None,
        )
        facts = self._application.fact_repository
        if declared is None or facts is None:
            return False
        groups = self._plan_mappings(plan)
        if groups is None:
            return False
        expected = {
            (request.filing.accession_number, item.normalized_field): item.decision_id
            for request, group in zip(plan.ingestions, groups, strict=True)
            for item in group
        }
        sources = {
            source.content_hash: source.accession_number
            for source in snapshot.source_records
            if source.role is SourceRole.FILING
        }
        for reference in declared.facts:
            fact = facts.get(reference.fact_id)
            if canonical_fact_digest(fact) != reference.fact_digest:
                raise ServiceError(
                    "DATA_RELEASE_FACT_MISMATCH",
                    "source preparation fact differs from the immutable release",
                    status_code=409,
                    retryable=False,
                )
            if fact.source.content_hash not in sources:
                return False
            accession = sources.get(fact.source.content_hash)
            key = (accession, fact.normalized_field)
            if key not in expected:
                key = (None, fact.normalized_field)
            if key not in expected or fact.mapping_decision_id != expected[key]:
                return False
        return True

    def _candidate_snapshot_available(
        self,
        plan: SourcePreparationPlan,
        candidate: DataReleaseCandidatePublishRequestV1,
    ) -> bool:
        for reference in candidate.manifest.snapshot_refs:
            try:
                snapshot = self._application.snapshot(reference.snapshot_id)
            except ServiceError as error:
                if error.code != "SNAPSHOT_NOT_FOUND":
                    raise
                continue
            if self._matches_plan(plan, snapshot) and self._matches_release(
                plan, snapshot, candidate.manifest
            ):
                return True
        return False

    @staticmethod
    def _matches_plan(plan: SourcePreparationPlan, snapshot: SourceSnapshotV1) -> bool:
        first = plan.ingestions[0]
        if any(
            getattr(snapshot, field) != getattr(first, field)
            for field in (
                "identity",
                "valuation_timestamp",
                "fiscal_period_selector",
                "parser_version",
                "policy_version",
                "taxonomy_manifest_id",
                "validation_profile_id",
            )
        ):
            return False
        expected = {request.filing.accession_number for request in plan.ingestions}
        if None not in expected:
            accessions = {
                source.accession_number
                for source in snapshot.source_records
                if source.role is SourceRole.FILING
            }
            if accessions != expected:
                return False
        return True

    def _activate(
        self,
        candidate: DataReleaseCandidatePublishRequestV1,
        *,
        actor_id: str,
        organization_id: str,
        correlation_id: str,
        plan: SourcePreparationPlan,
    ) -> None:
        config = self._application.config
        if (
            organization_id not in config.release_publish_authorized_organizations
            or organization_id not in config.release_activation_authorized_organizations
        ):
            raise ServiceError(
                "DATA_RELEASE_FORBIDDEN",
                "organization is not authorized to publish and activate releases",
                status_code=403,
                retryable=False,
            )
        if self._canary is None:
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "trusted candidate validation is not configured",
                status_code=503,
                retryable=False,
            )
        manifest = candidate.manifest
        try:
            active = self._application.active_data_release(manifest.profile_id)
        except ServiceError as error:
            if error.code != "DATA_RELEASE_NOT_ACTIVE":
                raise
            active = None
        self._canary.validate(manifest, candidate.verification)
        if not self._candidate_snapshot_available(plan, candidate):
            raise ValueError(
                "candidate does not match the requested source, date and fact mappings"
            )
        self._application.publish_data_release_candidate(
            manifest, candidate.verification
        )
        if (
            active is not None
            and active.manifest.manifest_digest == manifest.manifest_digest
        ):
            return
        command = DataReleaseActivationRequestV1(
            manifest_digest=manifest.manifest_digest,
            expected_revision=0 if active is None else active.active.revision,
            expected_manifest_digest=(
                None if active is None else active.manifest.manifest_digest
            ),
            operation="activate",
            command_id=sha256_digest(
                {
                    "operation": "source-preparation-activation-v1",
                    "manifest_digest": manifest.manifest_digest,
                    "expected_revision": 0
                    if active is None
                    else active.active.revision,
                    "actor_id": actor_id,
                    "organization_id": organization_id,
                    "correlation_id": correlation_id,
                }
            ),
            reason="validated source preparation candidate",
        )
        try:
            self._application.change_active_data_release(
                manifest.profile_id,
                command,
                actor_id=actor_id,
                organization_id=organization_id,
                correlation_id=correlation_id,
            )
        except ServiceError as error:
            if error.code != "DATA_RELEASE_POINTER_CONFLICT":
                raise
            current = self._application.active_data_release(manifest.profile_id)
            if current.manifest.manifest_digest != manifest.manifest_digest:
                raise

    def _persist(
        self, plan: SourcePreparationPlan, evidence: SourcePreparationEvidenceV1
    ) -> ArtifactPublicationV1:
        publication = self._artifacts.put_with_receipt(
            f"source-preparation-plan:{plan.digest}", plan
        )
        evidence = SourcePreparationEvidenceV1.model_validate(
            {
                **evidence.model_dump(),
                "source_plan_ref": ArtifactRefV1(
                    artifact_id=publication.artifact.artifact_id,
                    content_hash=publication.artifact.content_hash,
                    media_type=publication.artifact.media_type,
                    role="source-preparation-plan-v2"
                    if isinstance(plan, SourcePreparationPlanV2)
                    else plan.protocol,
                ),
            }
        )
        dependencies: tuple[str, ...] = (evidence.plan_digest,)
        if evidence.snapshot_manifest_digest is not None:
            dependencies += (evidence.snapshot_manifest_digest,)
        if evidence.data_release_manifest_digest is not None:
            dependencies += (evidence.data_release_manifest_digest,)
        dependencies += tuple(
            sorted(
                {
                    digest
                    for outcome in evidence.source_outcomes
                    for digest in (outcome.request_digest, outcome.manifest_digest)
                    if digest is not None
                }
            )
        )
        dependencies += tuple(
            sorted(
                {
                    outcome.mapping_evidence_ref.content_hash
                    for outcome in evidence.source_outcomes
                    if outcome.mapping_evidence_ref is not None
                }
            )
        )
        return self._artifacts.put_with_receipt(
            f"source-preparation:{sha256_digest(evidence)}",
            evidence,
            dependencies,
        )

    def _acquire_sources(
        self,
        plan: SourcePreparationPlan,
        *,
        actor_id: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
    ) -> tuple[tuple[SourceSnapshotV1, ...], tuple[SourceAcquisitionOutcomeV1, ...]]:
        if self._acquisition is None:
            raise ServiceError(
                "SOURCE_ACQUISITION_UNAVAILABLE",
                "SEC acquisition is not configured for this runner",
                status_code=503,
                retryable=False,
            )
        snapshots, outcomes = [], []
        for request in plan.ingestions:
            try:
                acquired = self._acquisition.execute(
                    request,
                    caller_principal=actor_id,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    deadline_at=deadline_at,
                    audit_reuse=False,
                )
                snapshot = None
                if acquired.quality_status is QualityStatus.VERIFIED:
                    if acquired.snapshot_id is None:
                        raise ValueError(
                            "verified acquisition must identify a stored snapshot"
                        )
                    snapshot = self._application.snapshot(acquired.snapshot_id)
            except ServiceError as error:
                if error.retryable or error.status_code != 422:
                    raise
                outcome = SourceAcquisitionOutcomeV1(
                    request_digest=sha256_digest(request),
                    accession_number=request.filing.accession_number,
                    quality_status=None,
                    issue_codes=(error.code,),
                    missing_evidence=tuple(sorted(request.required_fields)),
                )
            except SnapshotError as error:
                if error.retryable:
                    raise
                outcome = SourceAcquisitionOutcomeV1(
                    request_digest=sha256_digest(request),
                    accession_number=request.filing.accession_number,
                    quality_status=None,
                    issue_codes=(error.code,),
                    missing_evidence=tuple(sorted(request.required_fields)),
                )
            else:
                outcome = SourceAcquisitionOutcomeV1(
                    request_digest=sha256_digest(request),
                    accession_number=request.filing.accession_number,
                    quality_status=acquired.quality_status,
                    snapshot_id=acquired.snapshot_id,
                    manifest_digest=acquired.manifest_digest,
                    issue_codes=tuple(sorted(set(acquired.issue_codes))),
                    missing_evidence=tuple(sorted(set(acquired.missing_evidence))),
                    mapping_evidence_ref=self._mapping_evidence_ref(
                        acquired.mapping_evidence_ref
                    ),
                )
                if snapshot is not None:
                    snapshots.append(snapshot)
            outcomes.append(outcome)
        return tuple(snapshots), tuple(outcomes)

    def _mapping_evidence_ref(self, artifact_id: str | None) -> ArtifactRefV1 | None:
        if artifact_id is None:
            return None
        record = self._application.artifact_store.get(artifact_id)
        if record.status != "valid" or record.retention != "evidence":
            raise ValueError("source preparation requires valid mapping evidence")
        return ArtifactRefV1(
            artifact_id=record.artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role="automatic-mapping-batch-decision-v1",
        )

    def run(
        self,
        plan: SourcePreparationPlan,
        *,
        actor_id: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
        candidate: DataReleaseCandidatePublishRequestV1 | None = None,
        approval: CallerApprovalEnvelopeV1 | None = None,
    ) -> ArtifactPublicationV1:
        if not actor_id.strip() or not organization_id.strip():
            raise ValueError("runner requires an actor and organization")
        received_at = datetime.now(UTC)
        if deadline_at.tzinfo is None or deadline_at <= received_at:
            raise ValueError("runner deadline must be an unexpired zoned timestamp")
        guard_caller_approval(approval, caller_id=actor_id, received_at=received_at)
        if isinstance(plan, AutomaticSourcePreparationPlanV1):
            if self._acquisition is None:
                raise ServiceError(
                    "SOURCE_ACQUISITION_UNAVAILABLE",
                    "automatic source acquisition is not configured",
                    status_code=503,
                    retryable=False,
                )
            for request in plan.ingestions:
                self._acquisition.retained_acquisition(request)
        if candidate is not None and (
            candidate.manifest.profile_id != plan.release_profile_id
            or candidate.verification.source_revision != plan.source_revision
            or not set(plan.resolution_request().required_fields).issubset(
                candidate.manifest.required_fields
            )
            or not self._matches_release_mappings(plan, candidate.manifest)
        ):
            raise ValueError(
                "candidate does not match the plan profile, revision and mappings"
            )
        resolution = self._resolve(plan)
        if resolution is None and not (
            candidate is not None
            and self._candidate_snapshot_available(plan, candidate)
        ):
            snapshots, outcomes = self._acquire_sources(
                plan,
                actor_id=actor_id,
                organization_id=organization_id,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            if any(
                outcome.quality_status is not QualityStatus.VERIFIED
                for outcome in outcomes
            ):
                first_incomplete = next(
                    outcome
                    for outcome in outcomes
                    if outcome.quality_status is not QualityStatus.VERIFIED
                )
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="blocked",
                        snapshot_id=first_incomplete.snapshot_id,
                        snapshot_manifest_digest=first_incomplete.manifest_digest,
                        issue_codes=tuple(
                            sorted(
                                {
                                    code
                                    for outcome in outcomes
                                    for code in outcome.issue_codes
                                }
                            )
                        ),
                        missing_evidence=tuple(
                            sorted(
                                {
                                    field
                                    for outcome in outcomes
                                    for field in outcome.missing_evidence
                                }
                            )
                        ),
                        source_outcomes=outcomes,
                    ),
                )
            try:
                snapshot = snapshots[0]
                if len(snapshots) > 1:
                    repository = self._application.snapshot_repository
                    if repository is None:
                        raise ValueError(
                            "history composition requires a snapshot repository"
                        )
                    snapshot = compose_original_history(
                        repository,
                        tuple(item.snapshot_id for item in snapshots),
                        valuation_timestamp=plan.ingestions[0].valuation_timestamp,
                        fiscal_period_selector=plan.ingestions[
                            0
                        ].fiscal_period_selector,
                    )
            except ServiceError as error:
                if error.retryable or error.status_code != 422:
                    raise
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="blocked",
                        issue_codes=(error.code,),
                        source_outcomes=outcomes,
                    ),
                )
            except SnapshotError as error:
                if error.retryable:
                    raise
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="blocked",
                        issue_codes=(error.code,),
                        source_outcomes=outcomes,
                    ),
                )
            if candidate is not None and snapshot.snapshot_id not in {
                item.snapshot_id for item in candidate.manifest.snapshot_refs
            }:
                raise ValueError("candidate does not contain the acquired snapshot")
            resolution = self._resolve(plan)
            if candidate is None and resolution is None:
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="release_required",
                        snapshot_id=snapshot.snapshot_id,
                        snapshot_manifest_digest=snapshot.manifest_digest,
                        issue_codes=("DATA_RELEASE_REQUIRED",),
                    ),
                )
        if candidate is not None:
            self._activate(
                candidate,
                actor_id=actor_id,
                organization_id=organization_id,
                correlation_id=correlation_id,
                plan=plan,
            )
            resolution = self._resolve(plan)
            if resolution is None:
                raise ServiceError(
                    "DATA_RELEASE_SNAPSHOT_MISMATCH",
                    "activated candidate does not resolve the requested source and date",
                    status_code=409,
                    retryable=False,
                )
        assert resolution is not None
        if resolution.data_release_manifest_digest is None:
            raise ValueError("preparation requires an immutable data release")
        snapshot_digest = self._application.snapshot(
            resolution.snapshot_id
        ).manifest_digest
        preparation = self._application.prepare_valuation(
            ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=resolution.snapshot_id,
                data_release_manifest_digest=resolution.data_release_manifest_digest,
                model_id=plan.model_id,
            )
        )
        if preparation.status != "prepared" or preparation.input is None:
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    plan_digest=plan.digest,
                    status="blocked",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    issue_codes=preparation.issue_codes,
                    missing_evidence=preparation.missing_evidence,
                    preparation=preparation,
                ),
            )
        if approval is None:
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    plan_digest=plan.digest,
                    status="approval_required",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    preparation=preparation,
                ),
            )
        if approval.input_digest != preparation.input.input_digest:
            raise ValueError("caller approval is bound to a different valuation input")
        if approval.decision != "approved":
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    plan_digest=plan.digest,
                    status="blocked",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    issue_codes=("CALLER_APPROVAL_REJECTED",),
                    preparation=preparation,
                ),
            )
        calculation = self._application.calculate_valuation(
            preparation.input.model_copy(update={"caller_approval": approval}),
            correlation_id=correlation_id,
        )
        if not isinstance(calculation, UncertaintyReportV1):
            raise TypeError(
                "automatic preparation must retain the service uncertainty report"
            )
        calculation = calculation.model_copy(
            update={
                "base": calculation.base.model_copy(
                    update={"correlation_id": "persisted"}
                ),
                "scenario_results": tuple(
                    item.model_copy(update={"correlation_id": "persisted"})
                    for item in calculation.scenario_results
                ),
            }
        )
        return self._persist(
            plan,
            SourcePreparationEvidenceV1(
                source_revision=plan.source_revision,
                plan_digest=plan.digest,
                status="calculated",
                snapshot_id=resolution.snapshot_id,
                snapshot_manifest_digest=snapshot_digest,
                data_release_manifest_digest=resolution.data_release_manifest_digest,
                issue_codes=preparation.issue_codes,
                missing_evidence=preparation.missing_evidence,
                preparation=preparation,
                calculation=calculation,
            ),
        )


async def _run_command(args: argparse.Namespace) -> ArtifactPublicationV1:
    package_root = Path(__file__).resolve().parents[2]
    for root in (package_root, package_root.parent / "finance-agent-core"):
        root_string = str(root)
        if (
            root / "src/shared/internal_services"
        ).is_dir() and root_string not in sys.path:
            sys.path.insert(0, root_string)
    from .app import app

    plan = SOURCE_PREPARATION_PLAN.validate_json(args.plan.read_bytes())
    if plan.digest != args.plan_digest:
        raise ValueError("plan digest does not match the pinned input")
    candidate = (
        DataReleaseCandidatePublishRequestV1.model_validate_json(
            args.candidate.read_bytes()
        )
        if args.candidate
        else None
    )
    approval = (
        CallerApprovalEnvelopeV1.model_validate_json(args.approval.read_bytes())
        if args.approval
        else None
    )
    async with app.router.lifespan_context(app):
        application = app.state.application
        if not application.ready or app.state.metadata_store is None:
            raise RuntimeError(
                "Fundamental persistence and trust configuration are unavailable"
            )
        canary = None
        trust_roots_file = os.getenv("FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE")
        if trust_roots_file:
            canary = DataReleaseCanaryRunner(
                snapshot_repository=application.snapshot_repository,
                fact_repository=application.fact_repository,
                mapping_reader=app.state.metadata_store,
                artifact_reader=application.artifact_store,
                trust_roots=DataReleaseTrustRootsV1.from_file(Path(trust_roots_file)),
                quote_providers=application.quote_providers,
            )
        if isinstance(plan, AutomaticSourcePreparationPlanV1):
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )

            if (
                not trust_roots_file
                or args.machine_private_key is None
                or args.runtime_source_revision is None
                or app.state.sec_acquisition is None
            ):
                raise ValueError(
                    "automatic source preparation requires deployment trust, machine key, source revision and SEC runtime"
                )
            key = serialization.load_pem_private_key(
                args.machine_private_key.read_bytes(), password=None
            )
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("automatic mapping requires an Ed25519 deployment key")
            acquisition = app.state.sec_acquisition
            acquisition.automatic_mapping_authority = AutomaticSourceMappingAuthority(
                artifacts=application.artifact_store,
                content=acquisition.content_store,
                metadata=app.state.metadata_store,
                trust_roots=DataReleaseTrustRootsV1.from_file(Path(trust_roots_file)),
                private_key=key,
                source_revision=args.runtime_source_revision,
                taxonomy_cache_dir=acquisition.settings.taxonomy_cache_dir,
                taxonomy_cache_sha256=acquisition.settings.taxonomy_cache_sha256,
            )
        return SourcePreparationRunner(
            application=application,
            metadata=app.state.metadata_store,
            acquisition=app.state.sec_acquisition,
            artifacts=application.artifact_store,
            canary=canary,
        ).run(
            plan,
            actor_id=args.actor,
            organization_id=args.organization,
            correlation_id=f"source-preparation:{plan.digest[:32]}",
            deadline_at=datetime.now(UTC) + timedelta(seconds=args.timeout_seconds),
            candidate=candidate,
            approval=approval,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--machine-private-key", type=Path)
    parser.add_argument("--runtime-source-revision")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument(
        "--timeout-seconds", type=int, choices=range(1, 3601), default=300
    )
    args = parser.parse_args(argv)
    try:
        receipt = asyncio.run(_run_command(args))
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        ServiceError,
        DataReleaseError,
    ) as error:
        print(f"source preparation failed: {error}", file=sys.stderr)
        return 2
    print(canonical_bytes(receipt).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
