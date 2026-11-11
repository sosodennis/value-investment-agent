"""One-shot source preparation outside the serving API request path."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .application import FundamentalApplication
from .contracts import (
    CallerApprovalEnvelopeV1,
    InitialModelId,
    QualityStatus,
    SecIngestionRequestV1,
    SnapshotResolutionRequestV1,
    SnapshotResolutionV1,
    SourceRole,
    SourceSnapshotV1,
    StrictModel,
    ValuationEvidenceReadRequestV1,
)
from .data_releases import (
    DataReleaseActivationRequestV1,
    DataReleaseCandidatePublishRequestV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
)
from .operations import ServiceError
from .release_runner import DataReleaseCanaryRunner
from .replay import ArtifactPublicationV1
from .uncertainty import UncertaintyReportV1
from .serialization import canonical_bytes, sha256_digest
from .source_acquisition import SecAcquisitionUseCase
from .valuation_preparation import AutomaticValuationPreparationV1
from .valuation_requirements import valuation_requirements_profile


class SourcePreparationPlanV1(StrictModel):
    """Explicit deployment input; mappings and source pins stay service-owned."""

    protocol: Literal["source-preparation-v1"] = "source-preparation-v1"
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_profile_id: str = Field(min_length=1)
    model_id: InitialModelId
    ingestion: SecIngestionRequestV1

    @model_validator(mode="after")
    def requirements_match(self) -> SourcePreparationPlanV1:
        required = valuation_requirements_profile(self.model_id).required_fact_fields
        if set(self.ingestion.required_fields) != set(required):
            raise ValueError("source plan must cover the complete model requirements")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    def resolution_request(self) -> SnapshotResolutionRequestV1:
        return SnapshotResolutionRequestV1(
            contract_version="fundamental.v1",
            release_profile_id=self.release_profile_id,
            identity=self.ingestion.identity,
            valuation_timestamp=self.ingestion.valuation_timestamp,
            source_selection_policy="pit-v1",
            coverage_profile=self.ingestion.coverage_profile,
            required_fields=self.ingestion.required_fields,
        )


class SourcePreparationEvidenceV1(StrictModel):
    protocol: Literal["source-preparation-v1"] = "source-preparation-v1"
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    preparation: AutomaticValuationPreparationV1 | None = None
    calculation: UncertaintyReportV1 | None = None

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> SourcePreparationEvidenceV1:
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
        acquisition: SecAcquisitionUseCase | None,
        artifacts: PreparationArtifactWriter,
        canary: DataReleaseCanaryRunner | None,
    ) -> None:
        self._application = application
        self._acquisition = acquisition
        self._artifacts = artifacts
        self._canary = canary

    def _resolve(self, plan: SourcePreparationPlanV1) -> SnapshotResolutionV1 | None:
        try:
            resolution = self._application.resolve_snapshot(plan.resolution_request())
        except ServiceError as error:
            if error.code not in _EVIDENCE_MISS_CODES:
                raise
            return None
        snapshot = self._application.snapshot(resolution.snapshot_id)
        return resolution if self._matches_plan(plan, snapshot) else None

    def _candidate_snapshot_available(
        self,
        plan: SourcePreparationPlanV1,
        candidate: DataReleaseCandidatePublishRequestV1,
    ) -> bool:
        for reference in candidate.manifest.snapshot_refs:
            try:
                snapshot = self._application.snapshot(reference.snapshot_id)
            except ServiceError as error:
                if error.code != "SNAPSHOT_NOT_FOUND":
                    raise
                continue
            if self._matches_plan(plan, snapshot):
                return True
        return False

    @staticmethod
    def _matches_plan(
        plan: SourcePreparationPlanV1, snapshot: SourceSnapshotV1
    ) -> bool:
        if (
            snapshot.identity != plan.ingestion.identity
            or snapshot.valuation_timestamp != plan.ingestion.valuation_timestamp
        ):
            return False
        accession = plan.ingestion.filing.accession_number
        if accession is not None:
            accessions = {
                source.accession_number
                for source in snapshot.source_records
                if source.role is SourceRole.FILING
            }
            if accessions != {accession}:
                return False
        return True

    def _activate(
        self,
        candidate: DataReleaseCandidatePublishRequestV1,
        *,
        actor_id: str,
        organization_id: str,
        correlation_id: str,
        plan: SourcePreparationPlanV1,
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
        if not any(
            self._matches_plan(plan, self._application.snapshot(reference.snapshot_id))
            for reference in manifest.snapshot_refs
        ):
            raise ValueError("candidate does not contain the requested source and date")
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

    def _persist(self, evidence: SourcePreparationEvidenceV1) -> ArtifactPublicationV1:
        dependencies: tuple[str, ...] = (evidence.plan_digest,)
        if evidence.snapshot_manifest_digest is not None:
            dependencies += (evidence.snapshot_manifest_digest,)
        if evidence.data_release_manifest_digest is not None:
            dependencies += (evidence.data_release_manifest_digest,)
        return self._artifacts.put_with_receipt(
            f"source-preparation:{sha256_digest(evidence)}",
            evidence,
            dependencies,
        )

    def run(
        self,
        plan: SourcePreparationPlanV1,
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
        if deadline_at.tzinfo is None or deadline_at <= datetime.now(UTC):
            raise ValueError("runner deadline must be an unexpired zoned timestamp")
        if candidate is not None and (
            candidate.manifest.profile_id != plan.release_profile_id
            or candidate.verification.source_revision != plan.source_revision
            or not set(plan.ingestion.required_fields).issubset(
                candidate.manifest.required_fields
            )
        ):
            raise ValueError("candidate does not match the plan profile and revision")
        resolution = self._resolve(plan)
        if resolution is None and not (
            candidate is not None
            and self._candidate_snapshot_available(plan, candidate)
        ):
            if self._acquisition is None:
                raise ServiceError(
                    "SOURCE_ACQUISITION_UNAVAILABLE",
                    "SEC acquisition is not configured for this runner",
                    status_code=503,
                    retryable=False,
                )
            try:
                acquired = self._acquisition.execute(
                    plan.ingestion,
                    caller_principal=actor_id,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    deadline_at=deadline_at,
                )
            except ServiceError as error:
                if error.retryable or error.status_code != 422:
                    raise
                return self._persist(
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="blocked",
                        issue_codes=(error.code,),
                    )
                )
            if acquired.quality_status is not QualityStatus.VERIFIED:
                return self._persist(
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="blocked",
                        snapshot_id=acquired.snapshot_id,
                        snapshot_manifest_digest=acquired.manifest_digest,
                        issue_codes=tuple(sorted(set(acquired.issue_codes))),
                        missing_evidence=tuple(sorted(set(acquired.missing_evidence))),
                    )
                )
            if candidate is not None and acquired.snapshot_id not in {
                item.snapshot_id for item in candidate.manifest.snapshot_refs
            }:
                raise ValueError("candidate does not contain the acquired snapshot")
            resolution = self._resolve(plan)
            if candidate is None and resolution is None:
                return self._persist(
                    SourcePreparationEvidenceV1(
                        source_revision=plan.source_revision,
                        plan_digest=plan.digest,
                        status="release_required",
                        snapshot_id=acquired.snapshot_id,
                        snapshot_manifest_digest=acquired.manifest_digest,
                        issue_codes=("DATA_RELEASE_REQUIRED",),
                    )
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
                )
            )
        if approval is None:
            return self._persist(
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    plan_digest=plan.digest,
                    status="approval_required",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    preparation=preparation,
                )
            )
        if approval.input_digest != preparation.input.input_digest:
            raise ValueError("caller approval is bound to a different valuation input")
        if approval.caller_id != actor_id:
            raise ValueError("caller approval identity does not match the actor")
        if approval.decision != "approved":
            return self._persist(
                SourcePreparationEvidenceV1(
                    source_revision=plan.source_revision,
                    plan_digest=plan.digest,
                    status="blocked",
                    snapshot_id=resolution.snapshot_id,
                    snapshot_manifest_digest=snapshot_digest,
                    data_release_manifest_digest=resolution.data_release_manifest_digest,
                    issue_codes=("CALLER_APPROVAL_REJECTED",),
                    preparation=preparation,
                )
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
            )
        )


async def _run_command(args: argparse.Namespace) -> ArtifactPublicationV1:
    from .app import app

    plan = SourcePreparationPlanV1.model_validate_json(args.plan.read_bytes())
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
            )
        return SourcePreparationRunner(
            application=application,
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
