"""Compile saved original identity evidence into the existing source plan."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Literal

from pydantic import Field, model_validator

from .automatic_mapping import automatic_mapping_policy_digest
from .automatic_source_mapping import AutomaticSecIngestionRequestV1
from .command_artifacts import EvidenceArtifactStore
from .contracts import (
    FiscalPeriodSelectorV1,
    InitialModelId,
    SecFilingSelectorV1,
    StrictModel,
)
from .data_releases import ArtifactRefV1
from .original_preparation import OriginalPreparation
from .policies import initial_model_specs
from .preparation_runner import AutomaticSourcePreparationPlanV1
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .valuation_requirements import source_preparation_requirements_profile


class AutomaticSourcePlanConfigurationV1(StrictModel):
    """Deployment choices, without caller-supplied issuer or filing identity."""

    protocol: Literal["automatic-source-plan-configuration-v1"] = (
        "automatic-source-plan-configuration-v1"
    )
    model_id: InitialModelId
    release_profile_id: str = Field(min_length=1, max_length=128)
    coverage_profile: str = Field(min_length=1, max_length=128)
    evaluator_id: str = Field(min_length=1, max_length=128)
    mapping_version: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def supported_model(self) -> AutomaticSourcePlanConfigurationV1:
        source_preparation_requirements_profile(self.model_id)
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class OriginalSourcePlanRequestV1(StrictModel):
    protocol: Literal["original-source-plan-request-v1"] = (
        "original-source-plan-request-v1"
    )
    original_preparation: ArtifactRefV1
    configuration: AutomaticSourcePlanConfigurationV1
    runtime_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def original_reference(self) -> OriginalSourcePlanRequestV1:
        if (
            self.original_preparation.role != "sec-original-preparation-v1"
            or self.original_preparation.media_type != "application/json"
        ):
            raise ValueError("source compilation requires original preparation")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class OriginalSourcePlanEvidenceV1(StrictModel):
    protocol: Literal["original-source-plan-v1"] = "original-source-plan-v1"
    request: OriginalSourcePlanRequestV1
    plan: AutomaticSourcePreparationPlanV1 | None
    issue_codes: tuple[str, ...]
    retryable: bool

    @model_validator(mode="after")
    def plan_or_refusal(self) -> OriginalSourcePlanEvidenceV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("source compilation issues must be canonical")
        if (self.plan is None) != bool(self.issue_codes) or (
            self.plan is not None and self.retryable
        ):
            raise ValueError("source compilation needs a plan or retained refusal")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        if self.retryable:
            return f"original-source-plan-attempt:{self.digest}"
        return f"original-source-plan:{self.request.digest}"

    @property
    def plan_ref(self) -> ArtifactRefV1 | None:
        if self.plan is None:
            return None
        return ArtifactRefV1(
            artifact_id=f"source-preparation-plan:{self.plan.digest}",
            content_hash=self.plan.digest,
            media_type="application/json",
            role=self.plan.protocol,
        )

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.request.digest,
                    self.request.configuration.digest,
                    self.request.original_preparation.content_hash,
                    *((self.plan.digest,) if self.plan is not None else ()),
                }
            )
        )


class OriginalSourcePlan:
    def __init__(
        self,
        *,
        originals: OriginalPreparation,
        artifacts: EvidenceArtifactStore,
        compilation_lock: Callable[[str], AbstractContextManager[None]],
    ) -> None:
        self._originals = originals
        self._artifacts = artifacts
        self._lock = compilation_lock

    def _compile(
        self, request: OriginalSourcePlanRequestV1
    ) -> OriginalSourcePlanEvidenceV1:
        reference = request.original_preparation
        if (
            self._originals.reference(reference.artifact_id, reference.role)
            != reference
        ):
            raise SnapshotError("ORIGINAL_SOURCE_PLAN_INVALID", "original differs")
        prepared = self._originals.read(reference.artifact_id)
        codes = set(prepared.issue_codes)
        if not prepared.filings:
            codes.add("ORIGINAL_SOURCE_PLAN_FILINGS_MISSING")
        identities = {
            sha256_digest(item.identity)
            for item in prepared.filings
            if item.identity is not None
        }
        if len(identities) > 1:
            codes.add("ORIGINAL_HISTORY_IDENTITY_CONFLICT")
        if prepared.retryable and not codes:
            codes.add("ORIGINAL_SOURCE_PLAN_RETRYABLE")
        for item in prepared.filings:
            codes.update(item.issue_codes)
            if item.identity is None:
                codes.add("ORIGINAL_SOURCE_PLAN_IDENTITY_MISSING")
        plan = None
        if not codes:
            configuration = request.configuration
            profile = source_preparation_requirements_profile(configuration.model_id)
            model = next(
                model
                for model in initial_model_specs()
                if model.model_id == configuration.model_id
            )
            runtime = prepared.request.runtime
            ingestions = []
            for item in prepared.filings:
                validated = self._originals.read_validation(item.validation.artifact_id)
                original = validated.request
                identity = item.identity
                if identity is None:
                    raise SnapshotError(
                        "ORIGINAL_SOURCE_PLAN_INVALID", "original identity is missing"
                    )
                ingestions.append(
                    AutomaticSecIngestionRequestV1(
                        contract_version="fundamental.v1",
                        identity=identity,
                        cik=original.cik,
                        ticker=identity.security_id,
                        identity_basis="original-filing-dei-v1",
                        valuation_timestamp=original.valuation_timestamp,
                        fiscal_period_selector=FiscalPeriodSelectorV1(
                            mode="latest_complete", count=profile.history_window_years
                        ),
                        required_fields=profile.required_fact_fields,
                        source_selection_policy=original.source_selection_policy,
                        supplemental_filing_policy="sec-equity-award-proxy.v2",
                        coverage_profile=configuration.coverage_profile,
                        legal_use_profile="sec-public-us-v1",
                        filing=SecFilingSelectorV1(
                            accession_number=original.filing.accession_number,
                            forms=("10-K",),
                        ),
                        parser_version=runtime.arelle_version,
                        validation_profile_id=runtime.validation_profile_id,
                        taxonomy_manifest_id=runtime.taxonomy_manifest_id,
                        taxonomy_version=runtime.taxonomy_version,
                        policy_version=configuration.policy_version,
                        source_revision=request.runtime_source_revision,
                        evaluator_id=configuration.evaluator_id,
                        mapping_policy_digest=automatic_mapping_policy_digest(),
                        mapping_version=configuration.mapping_version,
                        model_id=configuration.model_id,
                        model_version=model.model_version,
                        requirements_digest=profile.digest,
                    )
                )
            plan = AutomaticSourcePreparationPlanV1(
                source_revision=request.runtime_source_revision,
                release_profile_id=configuration.release_profile_id,
                model_id=configuration.model_id,
                ingestions=tuple(
                    sorted(
                        ingestions, key=lambda item: item.filing.accession_number or ""
                    )
                ),
            )
        return OriginalSourcePlanEvidenceV1(
            request=request,
            plan=plan,
            issue_codes=tuple(sorted(codes)),
            retryable=prepared.retryable,
        )

    def _check_artifact(
        self,
        artifact_id: str,
        value: object,
        dependencies: tuple[str, ...] = (),
    ) -> None:
        record = self._artifacts.get(artifact_id)
        payload = self._artifacts.read(artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or record.dependency_hashes != dependencies
            or record.content_hash != hashlib.sha256(payload).hexdigest()
            or payload != canonical_bytes(value)
        ):
            raise SnapshotError(
                "ORIGINAL_SOURCE_PLAN_INVALID", "retained source plan differs"
            )

    def read(self, artifact_id: str) -> OriginalSourcePlanEvidenceV1:
        try:
            evidence = OriginalSourcePlanEvidenceV1.model_validate_json(
                self._artifacts.read(artifact_id)
            )
        except ValueError as error:
            raise SnapshotError(
                "ORIGINAL_SOURCE_PLAN_INVALID", "invalid retained source plan"
            ) from error
        self._check_artifact(artifact_id, evidence, evidence.dependencies)
        if artifact_id != evidence.artifact_id:
            raise SnapshotError("ORIGINAL_SOURCE_PLAN_INVALID", "plan identity differs")
        request = evidence.request
        self._check_artifact(f"original-source-plan-request:{request.digest}", request)
        self._check_artifact(
            f"source-plan-configuration:{request.configuration.digest}",
            request.configuration,
        )
        if evidence.plan_ref is not None:
            self._check_artifact(evidence.plan_ref.artifact_id, evidence.plan)
        if evidence != self._compile(request):
            raise SnapshotError(
                "ORIGINAL_SOURCE_PLAN_INVALID", "source compilation does not reproduce"
            )
        return evidence

    def execute(
        self, request: OriginalSourcePlanRequestV1
    ) -> tuple[OriginalSourcePlanEvidenceV1, ArtifactPublicationV1]:
        request = OriginalSourcePlanRequestV1.model_validate_json(
            canonical_bytes(request)
        )
        with self._lock(sha256_digest(("original-source-plan", request.digest))):
            artifact_id = f"original-source-plan:{request.digest}"
            try:
                self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                evidence = self.read(artifact_id)
                if evidence.request != request:
                    raise SnapshotError(
                        "ORIGINAL_SOURCE_PLAN_INVALID", "source plan request differs"
                    )
                return evidence, ArtifactPublicationV1(
                    artifact=self._artifacts.get(artifact_id), wrote=False
                )
            evidence = self._compile(request)
            self._artifacts.put_with_receipt(
                f"original-source-plan-request:{request.digest}", request
            )
            configuration = request.configuration
            self._artifacts.put_with_receipt(
                f"source-plan-configuration:{configuration.digest}", configuration
            )
            if evidence.plan_ref is not None:
                self._artifacts.put_with_receipt(
                    evidence.plan_ref.artifact_id, evidence.plan
                )
            publication = self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            self.read(evidence.artifact_id)
            return evidence, publication
