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
from .annual_history import AnnualHistoryError, resolve_annual_history
from .contracts import (
    CanonicalFactV1,
    CallerApprovalEnvelopeV1,
    InitialModelId,
    QualityStatus,
    SecIntegrityEvidenceV1,
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
from .issuer_market_preparation import (
    IssuerMarketPreparation,
    IssuerMarketPreparationEvidenceV1,
    IssuerMarketPreparationRequestV1,
)
from .release_runner import DataReleaseCanaryRunner
from .market_policy_deployment import MarketPolicyDeployment
from .policies import MetadataPolicyRepository, PolicyRecordV1
from .replay import ArtifactPublicationV1
from .uncertainty import UncertaintyReportV1
from .serialization import canonical_bytes, sha256_digest
from .source_acquisition import SecAcquisitionUseCase
from .snapshots import SnapshotError
from .public_acquisition import (
    PostgresPublicCaptureLock,
    PublicSourceAcquisition,
    PublicSourceAcquisitionEvidenceV1,
    PublicSourceAcquisitionRequestV1,
    PublicSourceCutoffV1,
)
from .quote_capture import quote_preparation_source_adapter
from .source_admission import SourceAdmissionV1
from .public_admission import (
    PublicSourceAdmission,
    PublicSourceAdmissionEvidenceV1,
    PublicSourceAdmissionRequestV1,
)
from .valuation_preparation import AutomaticValuationPreparationV1
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    select_released_facts,
    source_preparation_requirements_profile,
)
from .valuation_release_inputs import valuation_input_requirements
from .working_capital import (
    ValuationWorkingCapitalPolicyV1,
    assess_composite_working_capital,
)
from .working_capital_preparation import (
    ValuationWorkingCapitalRecipeV1,
    WorkingCapitalBindingV1,
    bind_working_capital_recipe,
)


SourceRequestT = TypeVar("SourceRequestT", bound=SecSourceRequestV1)


class _SourcePreparationPlan(StrictModel, Generic[SourceRequestT]):
    """Common issuer, chronology and runtime constraints for source plans."""

    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_profile_id: str = Field(min_length=1)
    model_id: InitialModelId
    ingestions: tuple[SourceRequestT, ...] = Field(min_length=1, max_length=6)
    public_sources: tuple[PublicSourceAcquisitionRequestV1, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    source_admissions: tuple[PublicSourceAdmissionRequestV1, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    public_source_cutoff: PublicSourceCutoffV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    issuer_market_policy: IssuerMarketPreparationRequestV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    valuation_working_capital_policy: ValuationWorkingCapitalPolicyV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    valuation_working_capital_recipe: ValuationWorkingCapitalRecipeV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @property
    def working_capital_spec(
        self,
    ) -> ValuationWorkingCapitalPolicyV1 | ValuationWorkingCapitalRecipeV1 | None:
        return (
            self.valuation_working_capital_policy
            or self.valuation_working_capital_recipe
        )

    @property
    def requirements_profile(self) -> ValuationRequirementsProfileV1:
        return source_preparation_requirements_profile(
            self.model_id,
            composite_inputs=self.working_capital_spec is not None,
        )

    @model_validator(mode="after")
    def requirements_match(self) -> _SourcePreparationPlan[SourceRequestT]:
        profile = self.requirements_profile
        recipe = self.valuation_working_capital_recipe
        if recipe is not None and (
            self.valuation_working_capital_policy is not None
            or recipe.model_id != self.model_id
            or any(
                item.accession_number
                not in {request.filing.accession_number for request in self.ingestions}
                or item.period_end > self.ingestions[0].valuation_timestamp.date()
                for item in recipe.periods
            )
        ):
            raise ValueError(
                "source recipe must exclusively pin the plan model and filings"
            )
        try:
            valuation_input_requirements(
                self.valuation_working_capital_policy, self.model_id
            )
        except DataReleaseError as error:
            raise ValueError(str(error)) from error
        required = set(profile.required_fact_fields)
        requested = {
            field for request in self.ingestions for field in request.required_fields
        }
        if not required <= requested <= required | set(profile.supporting_fact_fields):
            raise ValueError("source plan must cover the complete model requirements")
        first = self.ingestions[0]
        market = self.issuer_market_policy
        if market is not None and (
            market.source_revision != self.source_revision
            or market.classification_request.issuer_id != first.identity.issuer_id
            or market.classification_request.valuation_at != first.valuation_timestamp
            or market.market_policy.currency != first.identity.currency
            or market.classification_request.accession_number
            not in {item.filing.accession_number for item in self.ingestions}
        ):
            raise ValueError("issuer market request must pin the source plan context")
        cutoff = self.public_source_cutoff
        if cutoff is not None and (
            cutoff.valuation_at != first.valuation_timestamp
            or tuple(item.request for item in cutoff.captures) != self.public_sources
        ):
            raise ValueError(
                "current cutoff must pin the complete plan captures and date"
            )
        if len({request.digest for request in self.public_sources}) != len(
            self.public_sources
        ) or any(
            request.valuation_timestamp
            != (
                cutoff.requested_at if cutoff is not None else first.valuation_timestamp
            )
            for request in self.public_sources
        ):
            raise ValueError(
                "public source requests must be distinct and pin plan date"
            )
        if len({request.digest for request in self.source_admissions}) != len(
            self.source_admissions
        ) or any(
            request.valuation_at != first.valuation_timestamp
            or not set(
                (*request.source_request_digests, *request.terms_request_digests)
            )
            <= {item.digest for item in self.public_sources}
            for request in self.source_admissions
        ):
            raise ValueError(
                "source admissions must be distinct and pin plan captures and date"
            )
        if any(
            request.quote_selection is not None
            and (
                request.quote_selection.issuer_id != first.identity.issuer_id
                or request.quote_selection.security_id != first.identity.security_id
            )
            for request in self.source_admissions
        ):
            raise ValueError("quote selections must pin the source plan identity")
        if self.valuation_working_capital_policy is not None and any(
            item.issuer_id != first.identity.issuer_id
            or item.accession_number
            not in {request.filing.accession_number for request in self.ingestions}
            for item in self.valuation_working_capital_policy.inputs
        ):
            raise ValueError(
                "composite source inputs must pin the plan issuer and filings"
            )
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
            required_fields=self.requirements_profile.required_fact_fields,
        )


class SourcePreparationPlanV2(_SourcePreparationPlan[SecIngestionRequestV1]):
    """Explicit deployment input with pre-existing mapping decisions."""

    protocol: Literal["source-preparation-v2"] = "source-preparation-v2"

    @model_validator(mode="after")
    def mapping_references_match(self) -> SourcePreparationPlanV2:
        references: dict[str, SecMappingReferenceV1] = {}
        for request in self.ingestions:
            for reference in request.mappings:
                if (
                    self.working_capital_spec is not None
                    and reference.mapping_version
                    != self.working_capital_spec.mapping_version
                ):
                    raise ValueError(
                        "composite source plan must pin one mapping version"
                    )
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
                or request.requirements_digest != self.requirements_profile.digest
                or (
                    self.working_capital_spec is not None
                    and request.mapping_version
                    != self.working_capital_spec.mapping_version
                )
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
    source_coverage_status: QualityStatus | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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
        if self.source_coverage_status is not None and self.snapshot_id is None:
            raise ValueError("source coverage requires a stored snapshot")
        if (
            self.quality_status is QualityStatus.VERIFIED
            and self.source_coverage_status is not None
            and self.source_coverage_status is not QualityStatus.VERIFIED
        ):
            raise ValueError("verified acquisition requires verified source coverage")
        for values in (self.issue_codes, self.missing_evidence):
            if values != tuple(sorted(set(values))):
                raise ValueError("acquisition diagnostics must be canonical")
        return self


class SourcePreparationAcquisitionsV1(StrictModel):
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_outcomes: tuple[SourceAcquisitionOutcomeV1, ...] = Field(
        min_length=1, max_length=6
    )


class SourcePreparationEvidenceV1(StrictModel):
    protocol: Literal["source-preparation-v1"] = "source-preparation-v1"
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_plan_ref: ArtifactRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    working_capital_binding_ref: ArtifactRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    issuer_market_preparation_ref: ArtifactRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    market_policy_deployment_ref: ArtifactRefV1 | None = Field(
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
    public_source_outcomes: tuple[PublicSourceAcquisitionEvidenceV1, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    source_admission_outcomes: tuple[PublicSourceAdmissionEvidenceV1, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    public_source_cutoff: PublicSourceCutoffV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    preparation: AutomaticValuationPreparationV1 | None = None
    calculation: UncertaintyReportV1 | None = None

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> SourcePreparationEvidenceV1:
        deployment = self.market_policy_deployment_ref
        if deployment is not None and (
            deployment.role != "market-policy-deployment-v1"
            or deployment.media_type != "application/json"
            or self.snapshot_id is None
            or self.data_release_manifest_digest is None
        ):
            raise ValueError("market policy publication requires its exact release")
        market_ref = self.issuer_market_preparation_ref
        if market_ref is not None and (
            market_ref.role != "issuer-market-preparation-v1"
            or market_ref.media_type != "application/json"
            or self.snapshot_id is None
        ):
            raise ValueError(
                "issuer market evidence must bind a snapshot and JSON artifact"
            )
        if len({item.request.digest for item in self.source_admission_outcomes}) != len(
            self.source_admission_outcomes
        ) or (
            self.status != "blocked"
            and any(item.issue_codes for item in self.source_admission_outcomes)
        ):
            raise ValueError(
                "source admission outcomes require distinct evidenced decisions"
            )
        if self.public_source_cutoff is not None and (
            self.public_source_cutoff.captures != self.public_source_outcomes
        ):
            raise ValueError("current report must retain every cutoff capture")
        if self.status != "blocked" and any(
            outcome.issues_at(self.public_source_cutoff.valuation_at)
            if self.public_source_cutoff is not None
            else outcome.issue_codes
            for outcome in self.public_source_outcomes
        ):
            raise ValueError("unavailable required public sources block preparation")
        if len(
            {outcome.request.digest for outcome in self.public_source_outcomes}
        ) != len(self.public_source_outcomes):
            raise ValueError("public source outcomes must retain distinct requests")
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
            and outcome.source_coverage_status is not QualityStatus.VERIFIED
            for outcome in self.source_outcomes
        ):
            raise ValueError("unavailable source integrity requires a blocked outcome")
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
        public_acquisition: PublicSourceAcquisition | None = None,
        public_admission: PublicSourceAdmission | None = None,
        issuer_market_preparation: IssuerMarketPreparation | None = None,
        market_policy_deployment: MarketPolicyDeployment | None = None,
    ) -> None:
        self._application = application
        self._metadata = metadata
        self._acquisition = acquisition
        self._artifacts = artifacts
        self._canary = canary
        self._market_policy_deployment = market_policy_deployment
        self._public_acquisition = public_acquisition
        self._public_admission = public_admission
        self._issuer_market_preparation = issuer_market_preparation

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
                or retained.snapshot_id is None
                or retained.mapping_evidence_ref is None
            ):
                return None
            snapshot = self._application.snapshot(retained.snapshot_id)
            if (
                snapshot.manifest_digest != retained.manifest_digest
                or snapshot.coverage_status is not QualityStatus.VERIFIED
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
        policy = manifest.valuation_working_capital_policy
        recipe = plan.valuation_working_capital_recipe
        if recipe is None:
            if policy != plan.valuation_working_capital_policy:
                return False
        elif policy is None or any(
            getattr(policy, pin) != getattr(recipe, pin)
            for pin in (
                "model_id",
                "model_version",
                "requirements_profile_digest",
                "mapping_version",
            )
        ):
            return False
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
        if recipe is not None:
            for snapshot_ref in manifest.snapshot_refs:
                try:
                    snapshot = self._application.snapshot(snapshot_ref.snapshot_id)
                except ServiceError as error:
                    if error.code != "SNAPSHOT_NOT_FOUND":
                        raise
                    continue
                if self._matches_plan(plan, snapshot):
                    binding = self._bind_working_capital(plan, snapshot)
                    assert binding is not None
                    if binding.policy is None or binding.policy != policy:
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
        return self._candidate_snapshot(plan, candidate) is not None

    def _candidate_snapshot(
        self,
        plan: SourcePreparationPlan,
        candidate: DataReleaseCandidatePublishRequestV1,
    ) -> SourceSnapshotV1 | None:
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
                return snapshot
        return None

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

    def _retained_outcomes(
        self, plan: SourcePreparationPlan
    ) -> tuple[SourceAcquisitionOutcomeV1, ...]:
        acquisitions_id = f"source-preparation-acquisitions:{plan.digest}"
        try:
            record = self._application.artifact_store.get(acquisitions_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            return ()
        if record.status != "valid" or record.retention != "evidence":
            raise ValueError("retained acquisitions require valid evidence")
        retained = SourcePreparationAcquisitionsV1.model_validate_json(
            self._application.artifact_store.read(acquisitions_id)
        )
        if retained.plan_digest != plan.digest or tuple(
            outcome.request_digest for outcome in retained.source_outcomes
        ) != tuple(sha256_digest(request) for request in plan.ingestions):
            raise ValueError("retained acquisitions differ from source plan")
        return retained.source_outcomes

    def _persist(
        self, plan: SourcePreparationPlan, evidence: SourcePreparationEvidenceV1
    ) -> ArtifactPublicationV1:
        if plan.issuer_market_policy is not None and evidence.snapshot_id is not None:
            market, publication = self._prepare_issuer_market(
                plan,
                self._application.snapshot(evidence.snapshot_id),
                evidence.source_admission_outcomes,
            )
            if market.issue_codes and evidence.calculation is not None:
                raise ValueError(
                    "refused issuer market evidence cannot have a calculation"
                )
            evidence = SourcePreparationEvidenceV1.model_validate(
                {
                    **evidence.model_dump(),
                    "issuer_market_preparation_ref": ArtifactRefV1(
                        artifact_id=publication.artifact.artifact_id,
                        content_hash=publication.artifact.content_hash,
                        media_type=publication.artifact.media_type,
                        role=market.protocol,
                    ),
                    "status": "blocked" if market.issue_codes else evidence.status,
                    "issue_codes": tuple(
                        sorted(set(evidence.issue_codes) | set(market.issue_codes))
                    ),
                }
            )
        if evidence.public_source_cutoff != plan.public_source_cutoff:
            raise ValueError("preparation must retain the plan's public source cutoff")
        if (
            tuple(item.request for item in evidence.source_admission_outcomes)
            != plan.source_admissions
        ):
            raise ValueError("preparation must retain every planned source admission")
        if (
            tuple(outcome.request for outcome in evidence.public_source_outcomes)
            != plan.public_sources
        ):
            raise ValueError("preparation must retain every planned public source")
        publication = self._artifacts.put_with_receipt(
            f"source-preparation-plan:{plan.digest}", plan
        )
        binding_ref = None
        if (
            plan.valuation_working_capital_recipe is not None
            and evidence.snapshot_id is not None
            and self._plan_mappings(plan) is not None
        ):
            binding = self._bind_working_capital(
                plan, self._application.snapshot(evidence.snapshot_id)
            )
            assert binding is not None
            bound = self._artifacts.put_with_receipt(
                f"working-capital-binding:{binding.digest}",
                binding,
                (plan.digest, binding.recipe_digest, binding.snapshot_manifest_digest),
            )
            binding_ref = ArtifactRefV1(
                artifact_id=bound.artifact.artifact_id,
                content_hash=bound.artifact.content_hash,
                media_type=bound.artifact.media_type,
                role=binding.protocol,
            )
        if evidence.source_outcomes:
            self._artifacts.put_with_receipt(
                f"source-preparation-acquisitions:{plan.digest}",
                SourcePreparationAcquisitionsV1(
                    plan_digest=plan.digest, source_outcomes=evidence.source_outcomes
                ),
                (plan.digest,),
            )
        evidence = SourcePreparationEvidenceV1.model_validate(
            {
                **evidence.model_dump(),
                "working_capital_binding_ref": binding_ref,
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
        if evidence.public_source_cutoff is not None:
            dependencies += (evidence.public_source_cutoff.digest,)
        for outcome in evidence.public_source_outcomes:
            dependencies += (outcome.request.digest, outcome.digest)
            if outcome.source is not None:
                dependencies += (outcome.source.content_sha256,)
        for admission in evidence.source_admission_outcomes:
            dependencies += (admission.request.digest, admission.digest)
            dependencies += tuple(ref.content_hash for ref in admission.release_refs)
        if binding_ref is not None:
            dependencies += (binding_ref.content_hash,)
        if evidence.issuer_market_preparation_ref is not None:
            dependencies += (evidence.issuer_market_preparation_ref.content_hash,)
        if evidence.market_policy_deployment_ref is not None:
            dependencies += (evidence.market_policy_deployment_ref.content_hash,)
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
                if acquired.quality_status is QualityStatus.VERIFIED or (
                    len(plan.ingestions) > 1 and acquired.snapshot_id is not None
                ):
                    if acquired.snapshot_id is None:
                        raise ValueError(
                            "verified acquisition must identify a stored snapshot"
                        )
                    snapshot = self._application.snapshot(acquired.snapshot_id)
                    if snapshot.manifest_digest != acquired.manifest_digest:
                        raise SnapshotError(
                            "ACQUIRED_SNAPSHOT_MISMATCH",
                            "acquisition differs from its retained snapshot",
                        )
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
                    source_coverage_status=(
                        snapshot.coverage_status if snapshot is not None else None
                    ),
                    mapping_evidence_ref=self._mapping_evidence_ref(
                        acquired.mapping_evidence_ref
                    ),
                )
                if snapshot is not None and (
                    acquired.quality_status is QualityStatus.VERIFIED
                    or (
                        snapshot.coverage_status is QualityStatus.VERIFIED
                        and isinstance(
                            snapshot.sec_integrity_evidence, SecIntegrityEvidenceV1
                        )
                        and snapshot.sec_integrity_evidence.quality_decision == "pass"
                    )
                ):
                    snapshots.append(snapshot)
            outcomes.append(outcome)
        return tuple(snapshots), tuple(outcomes)

    def _plan_facts(
        self, plan: SourcePreparationPlan, snapshot: SourceSnapshotV1
    ) -> tuple[CanonicalFactV1, ...]:
        facts = self._application.fact_repository
        if facts is None:
            raise ValueError("history assessment requires a canonical fact repository")
        groups = self._plan_mappings(plan)
        if groups is None:
            raise SnapshotError(
                "HISTORY_MAPPING_EVIDENCE_UNAVAILABLE",
                "history assessment requires retained plan mappings",
            )
        mappings = {
            (request.filing.accession_number, item.normalized_field): item.decision_id
            for request, group in zip(plan.ingestions, groups, strict=True)
            for item in group
        }
        sources = {
            source.content_hash: source.accession_number
            for source in snapshot.source_records
            if source.role is SourceRole.FILING
        }
        return tuple(
            fact
            for fact in facts.list()
            if fact.source.content_hash in sources
            and fact.mapping_decision_id is not None
            and fact.mapping_decision_id
            == mappings.get((sources[fact.source.content_hash], fact.normalized_field))
        )

    def _bind_working_capital(
        self, plan: SourcePreparationPlan, snapshot: SourceSnapshotV1
    ) -> WorkingCapitalBindingV1 | None:
        recipe = plan.valuation_working_capital_recipe
        if recipe is None:
            return None
        return bind_working_capital_recipe(
            recipe, self._plan_facts(plan, snapshot), snapshot=snapshot
        )

    def _assess_history_requirements(
        self, plan: SourcePreparationPlan, snapshot: SourceSnapshotV1
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        binding = self._bind_working_capital(plan, snapshot)
        if binding is not None and binding.missing_evidence:
            return (
                "SOURCE_PREPARATION_WORKING_CAPITAL_INVALID",
            ), binding.missing_evidence
        policy = (
            binding.policy
            if binding is not None
            else plan.valuation_working_capital_policy
        )
        profile = plan.requirements_profile
        working_capital_inputs = policy.inputs if policy is not None else ()
        selected = select_released_facts(
            self._plan_facts(plan, snapshot),
            profile=profile,
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
            additional_fact_ids=tuple(
                fact_id for item in working_capital_inputs for fact_id in item.fact_ids
            ),
        )
        if selected.missing_fields:
            return selected.issue_codes, selected.missing_fields
        missing_composite = {
            missing
            for item in working_capital_inputs
            for missing in assess_composite_working_capital(
                item, selected.facts, snapshot=snapshot
            ).missing_evidence
        }
        if missing_composite:
            return ("SOURCE_PREPARATION_WORKING_CAPITAL_INVALID",), tuple(
                sorted(missing_composite)
            )
        try:
            history = resolve_annual_history(
                selected.facts,
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                profile=valuation_input_requirements(policy, plan.model_id),
                working_capital_inputs=working_capital_inputs,
            )
        except AnnualHistoryError as error:
            return (error.code,), ()
        if history.quality is QualityStatus.ABSTAIN:
            return history.issue_codes, tuple(
                f"{year}:{field}" for year, field in history.missing_fields
            )
        return (), ()

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

    def _acquire_public_sources(
        self, plan: SourcePreparationPlan, *, deadline_at: datetime
    ) -> tuple[PublicSourceAcquisitionEvidenceV1, ...]:
        if not plan.public_sources:
            return ()
        if self._public_acquisition is None:
            raise ServiceError(
                "PUBLIC_SOURCE_ACQUISITION_UNAVAILABLE",
                "required public source capture is not configured",
                status_code=503,
                retryable=False,
            )
        outcomes = []
        for request in plan.public_sources:
            if datetime.now(UTC) >= deadline_at:
                raise SnapshotError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "public source acquisition deadline expired",
                    retryable=True,
                )
            publication = self._public_acquisition.execute(request)
            outcomes.append(
                self._public_acquisition.read(publication.artifact.artifact_id)
            )
        if (
            plan.public_source_cutoff is not None
            and tuple(outcomes) != plan.public_source_cutoff.captures
        ):
            raise SnapshotError(
                "CURRENT_CAPTURE_MISMATCH",
                "current plan differs from retained source captures",
            )
        return tuple(outcomes)

    def _admit_public_sources(
        self,
        plan: SourcePreparationPlan,
        captures: tuple[PublicSourceAcquisitionEvidenceV1, ...],
        *,
        deadline_at: datetime,
    ) -> tuple[PublicSourceAdmissionEvidenceV1, ...]:
        if not plan.source_admissions:
            return ()
        if self._public_admission is None:
            raise ServiceError(
                "PUBLIC_SOURCE_ADMISSION_UNAVAILABLE",
                "required public source admission is not configured",
                status_code=503,
                retryable=False,
            )
        outcomes = []
        for request in plan.source_admissions:
            if datetime.now(UTC) >= deadline_at:
                raise SnapshotError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "source admission deadline expired",
                    retryable=True,
                )
            outcome, _ = self._public_admission.execute(request, captures)
            outcomes.append(outcome)
        return tuple(outcomes)

    @staticmethod
    def _matches_source_admissions(
        manifest: DataReleaseManifestV1,
        outcomes: tuple[PublicSourceAdmissionEvidenceV1, ...],
    ) -> bool:
        return all(
            reference in manifest.artifact_refs
            for outcome in outcomes
            for reference in outcome.release_refs
        )

    def _prepare_issuer_market(
        self,
        plan: SourcePreparationPlan,
        snapshot: SourceSnapshotV1,
        admissions: tuple[PublicSourceAdmissionEvidenceV1, ...],
    ) -> tuple[IssuerMarketPreparationEvidenceV1, ArtifactPublicationV1]:
        if plan.issuer_market_policy is None or self._issuer_market_preparation is None:
            raise ValueError("issuer market preparation is not configured")
        return self._issuer_market_preparation.execute(
            plan.issuer_market_policy,
            snapshot=snapshot,
            admissions=tuple(
                item.admission
                for item in admissions
                if isinstance(item.admission, SourceAdmissionV1)
            ),
        )

    def validate_candidate(
        self,
        plan: SourcePreparationPlan,
        candidate: DataReleaseCandidatePublishRequestV1 | None,
    ) -> None:
        """Reject incompatible release inputs before source acquisition."""
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
        market_policy_authorization: PolicyRecordV1 | None = None,
        market_policy_authorization_digest: str | None = None,
    ) -> ArtifactPublicationV1:
        if not actor_id.strip() or not organization_id.strip():
            raise ValueError("runner requires an actor and organization")
        received_at = datetime.now(UTC)
        if deadline_at.tzinfo is None or deadline_at <= received_at:
            raise ValueError("runner deadline must be an unexpired zoned timestamp")
        guard_caller_approval(approval, caller_id=actor_id, received_at=received_at)
        if (market_policy_authorization is None) != (
            market_policy_authorization_digest is None
        ):
            raise ValueError("market-policy authorization requires its exact digest")
        if market_policy_authorization is not None and (
            candidate is None or self._market_policy_deployment is None
        ):
            raise ValueError(
                "market policy publication requires a signed candidate and deployment authority"
            )
        deployment_ref = None
        if (
            plan.issuer_market_policy is not None
            and self._issuer_market_preparation is None
        ):
            raise ValueError(
                "source plan requires configured issuer market preparation"
            )
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
        outcomes = self._retained_outcomes(plan)
        self.validate_candidate(plan, candidate)
        public_outcomes = self._acquire_public_sources(plan, deadline_at=deadline_at)
        admission_outcomes = self._admit_public_sources(
            plan, public_outcomes, deadline_at=deadline_at
        )
        public_issues = tuple(
            sorted(
                {
                    code
                    for outcome in public_outcomes
                    for code in outcome.issues_at(
                        plan.ingestions[0].valuation_timestamp
                    )
                }
                | {
                    code
                    for admission in admission_outcomes
                    for code in admission.issue_codes
                }
                | (
                    {"SOURCE_ADMISSION_RELEASE_MISMATCH"}
                    if candidate is not None
                    and not self._matches_source_admissions(
                        candidate.manifest, admission_outcomes
                    )
                    else set()
                )
            )
        )
        if public_issues:
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    plan_digest=plan.digest,
                    status="blocked",
                    issue_codes=public_issues,
                    public_source_outcomes=public_outcomes,
                    public_source_cutoff=plan.public_source_cutoff,
                    source_admission_outcomes=admission_outcomes,
                ),
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
            incomplete = any(
                outcome.quality_status is not QualityStatus.VERIFIED
                for outcome in outcomes
            )
            if incomplete and (
                len(plan.ingestions) == 1 or len(snapshots) != len(outcomes)
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
                        public_source_outcomes=public_outcomes,
                        public_source_cutoff=plan.public_source_cutoff,
                        source_admission_outcomes=admission_outcomes,
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
                if (
                    len(snapshots) > 1
                    or plan.valuation_working_capital_recipe is not None
                ):
                    issues, missing = self._assess_history_requirements(plan, snapshot)
                    if issues:
                        return self._persist(
                            plan,
                            SourcePreparationEvidenceV1(
                                source_revision=plan.source_revision,
                                public_source_outcomes=public_outcomes,
                                public_source_cutoff=plan.public_source_cutoff,
                                source_admission_outcomes=admission_outcomes,
                                plan_digest=plan.digest,
                                status="blocked",
                                snapshot_id=snapshot.snapshot_id,
                                snapshot_manifest_digest=snapshot.manifest_digest,
                                issue_codes=issues,
                                missing_evidence=missing,
                                source_outcomes=outcomes,
                            ),
                        )
            except ServiceError as error:
                if error.retryable or error.status_code != 422:
                    raise
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        public_source_outcomes=public_outcomes,
                        public_source_cutoff=plan.public_source_cutoff,
                        source_admission_outcomes=admission_outcomes,
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
                        public_source_outcomes=public_outcomes,
                        public_source_cutoff=plan.public_source_cutoff,
                        source_admission_outcomes=admission_outcomes,
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
                        public_source_outcomes=public_outcomes,
                        public_source_cutoff=plan.public_source_cutoff,
                        source_admission_outcomes=admission_outcomes,
                        plan_digest=plan.digest,
                        status="release_required",
                        snapshot_id=snapshot.snapshot_id,
                        snapshot_manifest_digest=snapshot.manifest_digest,
                        issue_codes=("DATA_RELEASE_REQUIRED",),
                        source_outcomes=outcomes,
                    ),
                )
        if plan.issuer_market_policy is not None:
            market_manifest: DataReleaseManifestV1 | None
            if candidate is not None:
                market_snapshot = self._candidate_snapshot(plan, candidate)
                if market_snapshot is None:
                    raise ValueError(
                        "candidate does not contain the source-plan snapshot"
                    )
                market_manifest = candidate.manifest
            else:
                assert resolution is not None
                assert resolution.data_release_manifest_digest is not None
                market_snapshot = self._application.snapshot(resolution.snapshot_id)
                market_manifest = self._metadata.get_data_release_manifest(
                    resolution.data_release_manifest_digest
                )
            market, _ = self._prepare_issuer_market(
                plan, market_snapshot, admission_outcomes
            )
            market_issues = market.issue_codes
            if not market_issues and (
                market_manifest is None
                or any(
                    ref not in market_manifest.artifact_refs
                    for ref in market.release_refs
                )
            ):
                market_issues = ("ISSUER_MARKET_PREPARATION_RELEASE_MISMATCH",)
            if market_issues:
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        public_source_outcomes=public_outcomes,
                        public_source_cutoff=plan.public_source_cutoff,
                        source_admission_outcomes=admission_outcomes,
                        status="blocked",
                        snapshot_id=market_snapshot.snapshot_id,
                        snapshot_manifest_digest=market_snapshot.manifest_digest,
                        issue_codes=market_issues,
                        source_outcomes=outcomes,
                    ),
                )
        if candidate is not None:
            if market_policy_authorization is not None:
                assert self._market_policy_deployment is not None
                assert market_policy_authorization_digest is not None
                deployment_snapshot = self._candidate_snapshot(plan, candidate)
                if deployment_snapshot is None:
                    raise ValueError(
                        "policy candidate does not contain the requested snapshot"
                    )
                try:
                    deployment, publication = self._market_policy_deployment.publish(
                        candidate,
                        authorization=market_policy_authorization,
                        authorization_digest=market_policy_authorization_digest,
                        snapshot_id=deployment_snapshot.snapshot_id,
                        organization_id=organization_id,
                    )
                except DataReleaseError as error:
                    return self._persist(
                        plan,
                        SourcePreparationEvidenceV1(
                            source_revision=plan.source_revision,
                            plan_digest=plan.digest,
                            public_source_outcomes=public_outcomes,
                            public_source_cutoff=plan.public_source_cutoff,
                            source_admission_outcomes=admission_outcomes,
                            status="blocked",
                            snapshot_id=deployment_snapshot.snapshot_id,
                            snapshot_manifest_digest=deployment_snapshot.manifest_digest,
                            data_release_manifest_digest=candidate.manifest.manifest_digest,
                            issue_codes=(error.code,),
                            source_outcomes=outcomes,
                        ),
                    )
                deployment_ref = ArtifactRefV1(
                    artifact_id=publication.artifact.artifact_id,
                    content_hash=publication.artifact.content_hash,
                    media_type=publication.artifact.media_type,
                    role=deployment.protocol,
                )
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
        if admission_outcomes:
            manifest = self._metadata.get_data_release_manifest(
                resolution.data_release_manifest_digest
            )
            if manifest is None or not self._matches_source_admissions(
                manifest, admission_outcomes
            ):
                return self._persist(
                    plan,
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        public_source_outcomes=public_outcomes,
                        public_source_cutoff=plan.public_source_cutoff,
                        source_admission_outcomes=admission_outcomes,
                        plan_digest=plan.digest,
                        status="blocked",
                        snapshot_id=resolution.snapshot_id,
                        snapshot_manifest_digest=self._application.snapshot(
                            resolution.snapshot_id
                        ).manifest_digest,
                        data_release_manifest_digest=resolution.data_release_manifest_digest,
                        market_policy_deployment_ref=deployment_ref,
                        issue_codes=("SOURCE_ADMISSION_RELEASE_MISMATCH",),
                        source_outcomes=outcomes,
                    ),
                )
        snapshot_digest = self._application.snapshot(
            resolution.snapshot_id
        ).manifest_digest
        try:
            preparation = self._application.prepare_valuation(
                ValuationEvidenceReadRequestV1(
                    contract_version="fundamental.v1",
                    snapshot_id=resolution.snapshot_id,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    model_id=plan.model_id,
                )
            )
        except ServiceError as error:
            if error.retryable or error.status_code != 422:
                raise
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    public_source_outcomes=public_outcomes,
                    public_source_cutoff=plan.public_source_cutoff,
                    source_admission_outcomes=admission_outcomes,
                    plan_digest=plan.digest,
                    status="blocked",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    market_policy_deployment_ref=deployment_ref,
                    issue_codes=(error.code,),
                    source_outcomes=outcomes,
                ),
            )
        if preparation.status != "prepared" or preparation.input is None:
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    public_source_outcomes=public_outcomes,
                    public_source_cutoff=plan.public_source_cutoff,
                    source_admission_outcomes=admission_outcomes,
                    plan_digest=plan.digest,
                    status="blocked",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    market_policy_deployment_ref=deployment_ref,
                    issue_codes=preparation.issue_codes,
                    missing_evidence=preparation.missing_evidence,
                    source_outcomes=outcomes,
                    preparation=preparation,
                ),
            )
        if approval is None:
            return self._persist(
                plan,
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    public_source_outcomes=public_outcomes,
                    public_source_cutoff=plan.public_source_cutoff,
                    source_admission_outcomes=admission_outcomes,
                    plan_digest=plan.digest,
                    status="approval_required",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    market_policy_deployment_ref=deployment_ref,
                    source_outcomes=outcomes,
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
                    public_source_outcomes=public_outcomes,
                    public_source_cutoff=plan.public_source_cutoff,
                    source_admission_outcomes=admission_outcomes,
                    plan_digest=plan.digest,
                    status="blocked",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    market_policy_deployment_ref=deployment_ref,
                    issue_codes=("CALLER_APPROVAL_REJECTED",),
                    source_outcomes=outcomes,
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
                public_source_outcomes=public_outcomes,
                public_source_cutoff=plan.public_source_cutoff,
                source_admission_outcomes=admission_outcomes,
                plan_digest=plan.digest,
                status="calculated",
                snapshot_id=resolution.snapshot_id,
                snapshot_manifest_digest=snapshot_digest,
                data_release_manifest_digest=resolution.data_release_manifest_digest,
                market_policy_deployment_ref=deployment_ref,
                issue_codes=preparation.issue_codes,
                missing_evidence=preparation.missing_evidence,
                source_outcomes=outcomes,
                preparation=preparation,
                calculation=calculation,
            ),
        )


def _runtime_issuer_market_preparation(
    application: FundamentalApplication,
) -> IssuerMarketPreparation:
    from .sec_classification_snapshot import SecSnapshotClassificationSources
    from .sec_classification_source import SecSubmissionClassificationProvider
    from .sec_sic_damodaran_crosswalk import SecSicDamodaranIndustryCrosswalk
    from .sec_state_country_crosswalk import SecStateCountryCrosswalk

    if application.content_store is None:
        raise ValueError("issuer market preparation requires retained original bytes")
    return IssuerMarketPreparation(
        classification_provider=SecSubmissionClassificationProvider(),
        classification_sources=SecSnapshotClassificationSources(
            application.content_store
        ),
        country_provider=SecStateCountryCrosswalk(),
        industry_provider=SecSicDamodaranIndustryCrosswalk(),
        artifacts=application.artifact_store,
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
    authorization = (
        PolicyRecordV1.model_validate_json(
            args.market_policy_authorization.read_bytes()
        )
        if args.market_policy_authorization
        else None
    )
    if (authorization is None) != (args.market_policy_authorization_digest is None):
        raise ValueError("market-policy authorization requires its exact digest")
    if authorization is not None and (
        candidate is None
        or args.runtime_source_revision != plan.source_revision
        or sha256_digest(authorization) != args.market_policy_authorization_digest
    ):
        raise ValueError(
            "policy publication requires a signed candidate, exact authorization and runtime revision"
        )
    received_at = datetime.now(UTC)
    deadline_at = received_at + timedelta(seconds=args.timeout_seconds)
    if not args.actor.strip() or not args.organization.strip():
        raise ValueError("runner requires an actor and organization")
    guard_caller_approval(approval, caller_id=args.actor, received_at=received_at)
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
                macro_providers=application.macro_providers,
                reference_providers=application.reference_providers,
                source_use_policy=application.source_use_policy,
                policy_registry=application.policy_registry,
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
        public_acquisition = None
        if plan.public_sources:
            user_agent = os.getenv("FUNDAMENTAL_PUBLIC_SOURCE_USER_AGENT") or os.getenv(
                "FUNDAMENTAL_SEC_USER_AGENT"
            )
            if not user_agent or application.content_store is None:
                raise ValueError(
                    "public preparation requires a contact User-Agent and content store"
                )
            public_acquisition = PublicSourceAcquisition(
                provider=quote_preparation_source_adapter(
                    user_agent=user_agent,
                    policy=application.source_use_policy,
                    api_key_file=Path(
                        os.environ["FUNDAMENTAL_TWELVE_DATA_API_KEY_FILE"]
                    )
                    if os.getenv("FUNDAMENTAL_TWELVE_DATA_API_KEY_FILE")
                    else None,
                ),
                artifacts=application.artifact_store,
                content=application.content_store,
                capture_lock=PostgresPublicCaptureLock(app.state.metadata_store),
            )
        public_admission = None
        if plan.source_admissions:
            if public_acquisition is None or application.source_use_policy is None:
                raise ValueError(
                    "source admission requires acquisition and trusted policy"
                )
            public_admission = PublicSourceAdmission(
                acquisitions=public_acquisition,
                artifacts=application.artifact_store,
                policy=application.source_use_policy,
                macro_providers=application.macro_providers,
                reference_providers=application.reference_providers,
                quote_providers=application.quote_providers,
            )
        policy_deployment = None
        if authorization is not None:
            if (
                not trust_roots_file
                or application.policy_registry is None
                or application.source_use_policy is None
                or application.fact_repository is None
                or application.snapshot_repository is None
            ):
                raise ValueError(
                    "market-policy publication requires configured deployment trust and evidence repositories"
                )
            policy_deployment = MarketPolicyDeployment(
                policies=MetadataPolicyRepository(app.state.metadata_store),
                registry=application.policy_registry,
                snapshots=application.snapshot_repository,
                facts=application.fact_repository,
                mappings=app.state.metadata_store,
                artifacts=application.artifact_store,
                trust_roots=DataReleaseTrustRootsV1.from_file(Path(trust_roots_file)),
                source_use_policy=application.source_use_policy,
                macro_providers=application.macro_providers,
                reference_providers=application.reference_providers,
                quote_providers=application.quote_providers,
                authorized_organizations=application.config.release_publish_authorized_organizations,
                runtime_source_revision=args.runtime_source_revision,
            )
        runner = SourcePreparationRunner(
            application=application,
            metadata=app.state.metadata_store,
            acquisition=app.state.sec_acquisition,
            artifacts=application.artifact_store,
            canary=canary,
            market_policy_deployment=policy_deployment,
            public_acquisition=public_acquisition,
            public_admission=public_admission,
            issuer_market_preparation=_runtime_issuer_market_preparation(application)
            if plan.issuer_market_policy is not None
            else None,
        )
        runner.validate_candidate(plan, candidate)
        if args.current:
            from .current_preparation import (
                CurrentSourcePreparation,
                CurrentSourcePreparationRequestV1,
            )

            if public_acquisition is None:
                raise ValueError("current preparation requires public source requests")
            selected, publication = CurrentSourcePreparation(
                acquisitions=public_acquisition,
                artifacts=application.artifact_store,
                selection_lock=PostgresPublicCaptureLock(app.state.metadata_store),
            ).execute(
                CurrentSourcePreparationRequestV1(template=plan),
                deadline_at=deadline_at,
            )
            if selected.plan is None:
                return publication
            plan = selected.plan
        return runner.run(
            plan,
            actor_id=args.actor,
            organization_id=args.organization,
            correlation_id=f"source-preparation:{plan.digest[:32]}",
            deadline_at=deadline_at,
            candidate=candidate,
            approval=approval,
            market_policy_authorization=authorization,
            market_policy_authorization_digest=args.market_policy_authorization_digest,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument(
        "--current",
        action="store_true",
        help="capture current public originals, then freeze and reuse the effective valuation plan",
    )
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--market-policy-authorization", type=Path)
    parser.add_argument("--market-policy-authorization-digest")
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
    except SnapshotError as error:
        print(
            canonical_bytes(
                {
                    "protocol": "source-preparation-error-v1",
                    "plan_digest": args.plan_digest,
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                    "evidence_ref": error.evidence_ref,
                }
            ).decode("utf-8"),
            file=sys.stderr,
        )
        return 2
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
