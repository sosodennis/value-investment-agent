"""Authorize reusable compiler settings and reproduce their issuer decisions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from .automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_REF_PREFIX,
    assemble_authorized_market_policy_record,
)
from .command_artifacts import EvidenceArtifactStore
from .contracts import SourceSnapshotV1, StrictModel
from .current_preparation import (
    CurrentSourcePreparation,
    CurrentSourcePreparationRequestV1,
)
from .data_releases import ArtifactRefV1, DataReleaseError, DataReleaseManifestV1
from .issuer_market_preparation import (
    IssuerMarketPreparation,
    IssuerMarketPreparationEvidenceV1,
)
from .original_source_plan import OriginalSourcePlan
from .policies import ModelSpecV1, PolicyRecordV1
from .public_acquisition import PublicSourceAcquisition
from .public_admission import PublicSourceAdmission
from .serialization import canonical_bytes, sha256_digest
from .source_admission import SourceAdmissionV1
from .source_plan_contracts import AutomaticSourcePreparationPlanV1


class AutomaticMarketPolicyAuthorizationV1(StrictModel):
    """Deployment approval of settings, independent of supplied source artifacts."""

    protocol: Literal["automatic-market-policy-authorization-v1"] = (
        "automatic-market-policy-authorization-v1"
    )
    source_plan_configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AutomaticMarketAuthorityRuntime:
    compiler: OriginalSourcePlan
    current: CurrentSourcePreparation
    acquisitions: PublicSourceAcquisition
    admissions: PublicSourceAdmission
    preparation: IssuerMarketPreparation


ModelT = TypeVar("ModelT", bound=BaseModel)


def _read(
    artifacts: EvidenceArtifactStore, ref: ArtifactRefV1, model: type[ModelT]
) -> ModelT:
    try:
        record = artifacts.get(ref.artifact_id)
        raw = artifacts.read(ref.artifact_id)
        value = model.model_validate_json(raw)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or ref.media_type != record.media_type
            or ref.content_hash != record.content_hash
            or hashlib.sha256(raw).hexdigest() != ref.content_hash
            or raw != canonical_bytes(value)
        ):
            raise ValueError("market authority requires canonical retained evidence")
        return value
    except (KeyError, OSError, ValueError) as error:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_EVIDENCE_INVALID",
            "market authority cannot reproduce its retained evidence",
        ) from error


def authorize_compiled_market_policy(
    manifest: DataReleaseManifestV1,
    *,
    authorization: AutomaticMarketPolicyAuthorizationV1,
    model: ModelSpecV1,
    snapshot: SourceSnapshotV1,
    admissions: tuple[SourceAdmissionV1, ...],
    artifacts: EvidenceArtifactStore,
    owners: AutomaticMarketAuthorityRuntime,
    source_plan: AutomaticSourcePreparationPlanV1,
    source_revision: str,
) -> PolicyRecordV1:
    """Return an unpublished policy; signing and the complete canary remain required."""
    refs = tuple(
        ref
        for ref in manifest.artifact_refs
        if ref.role == "issuer-market-preparation-v1"
    )
    if len(refs) != 1:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_EVIDENCE_INVALID",
            "automatic authority requires one exact issuer market preparation",
        )
    evidence = _read(artifacts, refs[0], IssuerMarketPreparationEvidenceV1)
    request = evidence.request
    identity = request.automatic_policy_identity
    if identity is None:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_COMPILER_REQUIRED",
            "automatic authority requires a compiler-scoped market request",
        )
    compiled = owners.compiler.read(
        "original-source-plan:" + identity.compiler_request_digest
    )
    compiler = compiled.request
    expected_plan = compiled.plan
    if expected_plan is not None and source_plan.public_source_cutoff is not None:
        current_request = CurrentSourcePreparationRequestV1(template=expected_plan)
        selected = owners.current.read(
            "current-source-preparation:" + current_request.digest
        )
        if selected.request != current_request or not isinstance(
            selected.plan, AutomaticSourcePreparationPlanV1
        ):
            raise DataReleaseError(
                "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH",
                "current selection differs from the reproduced compiler plan",
            )
        expected_plan = selected.plan
    if (
        compiler.digest != identity.compiler_request_digest
        or compiler.configuration.digest
        != authorization.source_plan_configuration_digest
        or compiler.runtime_source_revision != source_revision
        or request.source_revision != source_revision
        or evidence.snapshot_id != snapshot.snapshot_id
        or evidence.snapshot_manifest_digest != snapshot.manifest_digest
        or identity.model_id != model.model_id
        or identity.model_version != model.model_version
        or identity.profile_id != model.profile_id
        or not any(
            ref.snapshot_id == snapshot.snapshot_id
            and ref.manifest_digest == snapshot.manifest_digest
            for ref in manifest.snapshot_refs
        )
        or source_plan != expected_plan
        or request != source_plan.issuer_market_policy
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH",
            "market request differs from deployment-approved compiler settings",
        )
    captures = tuple(
        owners.acquisitions.read("public-source-acquisition:" + item.digest)
        for item in source_plan.public_sources
    )
    if tuple(item.request for item in captures) != source_plan.public_sources:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH",
            "market captures differ from the reproduced compiler plan",
        )
    reproduced_admissions = []
    for planned in source_plan.source_admissions:
        admitted, _ = owners.admissions.execute(planned, captures)
        if admitted.issue_codes or any(
            ref not in manifest.artifact_refs for ref in admitted.release_refs
        ):
            raise DataReleaseError(
                "AUTOMATIC_MARKET_AUTHORITY_REPLAY_MISMATCH",
                "market admissions must cover the exact compiled capture closure",
            )
        if isinstance(admitted.admission, SourceAdmissionV1):
            reproduced_admissions.append(admitted.admission)
    if {item.output_digest for item in reproduced_admissions} != {
        item.output_digest for item in admissions
    }:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_REPLAY_MISMATCH",
            "release admissions differ from the deployment-approved source plan",
        )
    reproduced, _ = owners.preparation.execute(
        request, snapshot=snapshot, admissions=admissions
    )
    if (
        reproduced != evidence
        or reproduced.issue_codes
        or any(ref not in manifest.artifact_refs for ref in reproduced.release_refs)
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_AUTHORITY_REPLAY_MISMATCH",
            "market classification, crosswalks and sources must reproduce exactly",
        )
    plan = reproduced.market.plan_decision.plan
    assert plan is not None
    payload = {
        "contract_version": "fundamental.v1",
        "policy_id": plan.policy_id,
        "policy_version": request.market_policy.policy_version,
        "profile_id": model.profile_id,
        "model_id": model.model_id,
        "model_version": model.model_version,
        "issuer_id": snapshot.identity.issuer_id,
        "assumptions": None,
        "market_inputs": None,
        "source_refs": (
            "urn:fundamental:automatic-market-authorization:"
            + sha256_digest(authorization),
            AUTOMATIC_MARKET_POLICY_REF_PREFIX + sha256_digest(reproduced.market),
            sha256_digest(plan),
            sha256_digest(request.market_policy.terminal_growth_plan),
        ),
        "effective_at": snapshot.valuation_timestamp,
        "status": "active",
    }
    return assemble_authorized_market_policy_record(
        manifest,
        authorization=PolicyRecordV1.model_validate(
            {**payload, "policy_digest": sha256_digest(payload)}
        ),
        model=model,
        snapshot=snapshot,
        admissions=admissions,
        artifacts=artifacts,
        expected_source_revision=source_revision,
    )
