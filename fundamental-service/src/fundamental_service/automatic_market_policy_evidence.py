"""Reproduce automatic market-policy assembly at the trusted release boundary.

Source admissions are reproduced by the caller's configured provider ports. The
deployment policy authorizes this exact decision and both selection plans;
retaining a decision does not itself approve an issuer classification.
"""

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .automatic_market_policy import (
    AutomaticMarketPolicyDecisionV1,
    AutomaticMarketPolicyPolicyV1,
    evaluate_automatic_market_policy,
)
from .contracts import SourceSnapshotV1
from .data_releases import DataReleaseError, DataReleaseManifestV1
from .issuer_market_policy_plan import IssuerMarketReferencePlanDecisionV1
from .market_reference_evidence import read_release_market_reference_plan
from .policies import ModelSpecV1, PolicyRecordV1, PolicyRegistry
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .source_admission import SourceAdmissionV1
from .source_admission_evidence import AdmissionArtifactReader
from .terminal_growth_evidence import read_release_terminal_growth_plan

AUTOMATIC_MARKET_POLICY_ROLE = "automatic_market_policy_decision"
AUTOMATIC_MARKET_POLICY_REF_PREFIX = "urn:fundamental:automatic-market-policy:"


class AutomaticMarketPolicyEvidenceV1(BaseModel):
    """Replay input and result; no provider implementation or signing key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["automatic-market-policy-evidence-v1"] = (
        "automatic-market-policy-evidence-v1"
    )
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_decision: IssuerMarketReferencePlanDecisionV1
    decision: AutomaticMarketPolicyDecisionV1


def build_automatic_market_policy_evidence(
    *,
    source_revision: str,
    plan_decision: IssuerMarketReferencePlanDecisionV1,
    policy: AutomaticMarketPolicyPolicyV1,
    admissions: tuple[SourceAdmissionV1, ...],
) -> AutomaticMarketPolicyEvidenceV1:
    """Run the approved evaluator and return its canonical release artifact."""
    decision = evaluate_automatic_market_policy(
        plan_decision, policy=policy, admissions=admissions
    )
    return AutomaticMarketPolicyEvidenceV1(
        source_revision=source_revision,
        plan_decision=plan_decision,
        decision=decision,
    )


def requires_automatic_market_policy(policy: PolicyRecordV1 | None) -> bool:
    return policy is not None and any(
        ref.startswith(AUTOMATIC_MARKET_POLICY_REF_PREFIX) for ref in policy.source_refs
    )


def _read_automatic_market_policy(
    manifest: DataReleaseManifestV1,
    *,
    artifacts: AdmissionArtifactReader,
) -> AutomaticMarketPolicyEvidenceV1 | None:
    refs = tuple(
        ref
        for ref in manifest.artifact_refs
        if ref.role == AUTOMATIC_MARKET_POLICY_ROLE
    )
    if not refs:
        return None
    if len(refs) != 1:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_EVIDENCE_AMBIGUOUS",
            "release requires exactly one automatic market-policy decision",
        )
    ref = refs[0]
    raw = artifacts.read(ref.artifact_id)
    if (
        ref.media_type != "application/json"
        or sha256(raw).hexdigest() != ref.content_hash
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISMATCH",
            "automatic market-policy evidence differs from released bytes",
        )
    try:
        evidence = AutomaticMarketPolicyEvidenceV1.model_validate_json(raw)
    except ValueError as error:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_EVIDENCE_INVALID",
            "automatic market-policy evidence violates its contract",
        ) from error
    if canonical_bytes(evidence) != raw:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_EVIDENCE_NONCANONICAL",
            "automatic market-policy evidence requires canonical serialization",
        )
    return evidence


def load_release_automatic_market_policy(
    manifest: DataReleaseManifestV1,
    *,
    snapshot: SourceSnapshotV1,
    policy: PolicyRecordV1 | None,
    admissions: tuple[SourceAdmissionV1, ...],
    artifacts: AdmissionArtifactReader,
    expected_source_revision: str | None = None,
) -> AutomaticMarketPolicyEvidenceV1 | None:
    """Verify the declared assembly without granting new policy authority."""
    evidence = _read_automatic_market_policy(manifest, artifacts=artifacts)
    if evidence is None:
        if requires_automatic_market_policy(policy):
            raise DataReleaseError(
                "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISSING",
                "automatic deployment policy requires its released decision",
            )
        return None
    if (
        policy is None
        or AUTOMATIC_MARKET_POLICY_REF_PREFIX + sha256_digest(evidence)
        not in policy.source_refs
        or sum(
            item.startswith(AUTOMATIC_MARKET_POLICY_REF_PREFIX)
            for item in policy.source_refs
        )
        != 1
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_UNAPPROVED",
            "deployment policy must authorize the exact automatic decision",
        )
    decision = evidence.decision
    if (
        expected_source_revision is not None
        and evidence.source_revision != expected_source_revision
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_REVISION_MISMATCH",
            "automatic market-policy revision differs from release verification",
        )
    plan = read_release_market_reference_plan(manifest, artifacts=artifacts)
    terminal_plan = read_release_terminal_growth_plan(manifest, artifacts=artifacts)
    if (
        decision.issuer_id != snapshot.identity.issuer_id
        or policy.issuer_id != decision.issuer_id
        or decision.valuation_at != snapshot.valuation_timestamp
        or decision.policy.currency != snapshot.identity.currency
        or decision.policy.policy_version != policy.policy_version
        or decision.policy.terminal_growth_plan.policy_id != policy.policy_id
        or (
            policy.data_release_manifest_digest is not None
            and policy.data_release_manifest_digest != manifest.manifest_digest
        )
        or evidence.plan_decision.plan is None
        or plan != evidence.plan_decision.plan
        or terminal_plan != decision.policy.terminal_growth_plan
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH",
            "automatic policy differs from the issuer, date or released plans",
        )
    if (
        sha256_digest(plan) not in policy.source_refs
        or sha256_digest(terminal_plan) not in policy.source_refs
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_PLAN_UNAPPROVED",
            "deployment policy must authorize both exact selection plans",
        )
    try:
        evaluate_automatic_market_policy(
            evidence.plan_decision,
            policy=decision.policy,
            admissions=admissions,
            expected=decision,
        )
    except (ValueError, SnapshotError) as error:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_REPLAY_MISMATCH",
            "automatic market-policy decision cannot be reproduced",
        ) from error
    if decision.status != "approved" or decision.inputs != policy.market_inputs:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_INPUTS_MISMATCH",
            "deployment inputs differ from the complete reproduced decision",
        )
    return evidence


def assemble_authorized_market_policy_record(
    manifest: DataReleaseManifestV1,
    *,
    authorization: PolicyRecordV1,
    model: ModelSpecV1,
    snapshot: SourceSnapshotV1,
    admissions: tuple[SourceAdmissionV1, ...],
    artifacts: AdmissionArtifactReader,
    expected_source_revision: str,
) -> PolicyRecordV1:
    """Build an unpublished candidate from an operator's exact authorization.

    The authorization must already pin the decision and both selection plans.
    Admissions must have been reproduced by the configured source-use owner.
    This factory never installs a policy or changes a published identity; the
    trusted publisher and signed release canary still own those later gates.
    """
    authorization = PolicyRecordV1.model_validate_json(canonical_bytes(authorization))
    model = ModelSpecV1.model_validate_json(canonical_bytes(model))
    if (
        authorization.model_id != model.model_id
        or authorization.model_version != model.model_version
        or authorization.profile_id != model.profile_id
        or model.lifecycle == "retired"
    ):
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_MODEL_MISMATCH",
            "market-policy authorization must pin the supplied model and profile",
        )
    evidence = _read_automatic_market_policy(manifest, artifacts=artifacts)
    if evidence is None:
        raise DataReleaseError(
            "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISSING",
            "market-policy assembly requires its released decision",
        )
    if authorization.data_release_manifest_digest not in {
        None,
        manifest.manifest_digest,
    }:
        raise DataReleaseError(
            "POLICY_DATA_RELEASE_MISMATCH",
            "operator authorization is bound to a different data release",
        )
    payload = authorization.model_dump(exclude={"policy_digest"})
    payload["data_release_manifest_digest"] = manifest.manifest_digest
    if authorization.market_inputs is None:
        payload["market_inputs"] = evidence.decision.inputs
    candidate = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    load_release_automatic_market_policy(
        manifest,
        snapshot=snapshot,
        policy=candidate,
        admissions=admissions,
        artifacts=artifacts,
        expected_source_revision=expected_source_revision,
    )
    return PolicyRegistry(models=(model,), policies=(candidate,)).select_policy(
        model_id=model.model_id,
        model_version=model.model_version,
        valuation_timestamp=snapshot.valuation_timestamp,
        policy_id=candidate.policy_id,
        issuer_id=snapshot.identity.issuer_id,
        data_release_manifest_digest=manifest.manifest_digest,
    )
