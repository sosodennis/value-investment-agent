"""Reproduce the deployment-pinned issuer reference plan in a signed release."""

from hashlib import sha256

from .contracts import SourceSnapshotV1
from .data_releases import DataReleaseError, DataReleaseManifestV1
from .market_reference_selection import (
    IssuerMarketReferencePlanV1,
    IssuerMarketReferenceSelectionV1,
    select_issuer_market_references,
)
from .policies import PolicyRecordV1
from .serialization import canonical_bytes
from .source_admission import SourceAdmissionV1
from .source_admission_evidence import AdmissionArtifactReader

MARKET_REFERENCE_PLAN_ROLE = "issuer_market_reference_plan"


def read_release_market_reference_plan(
    manifest: DataReleaseManifestV1,
    *,
    artifacts: AdmissionArtifactReader,
) -> IssuerMarketReferencePlanV1 | None:
    """Read one content-bound plan without approving its classification."""
    references = tuple(
        ref for ref in manifest.artifact_refs if ref.role == MARKET_REFERENCE_PLAN_ROLE
    )
    if not references:
        return None
    if len(references) != 1:
        raise DataReleaseError(
            "MARKET_REFERENCE_PLAN_AMBIGUOUS",
            "release requires exactly one issuer reference plan",
        )
    ref = references[0]
    raw = artifacts.read(ref.artifact_id)
    if (
        ref.media_type != "application/json"
        or sha256(raw).hexdigest() != ref.content_hash
    ):
        raise DataReleaseError(
            "MARKET_REFERENCE_PLAN_MISMATCH",
            "issuer reference plan differs from the pinned release",
        )
    try:
        plan = IssuerMarketReferencePlanV1.model_validate_json(raw)
    except ValueError as error:
        raise DataReleaseError(
            "MARKET_REFERENCE_PLAN_INVALID", "issuer reference plan is invalid"
        ) from error
    if canonical_bytes(plan) != raw:
        raise DataReleaseError(
            "MARKET_REFERENCE_PLAN_NONCANONICAL",
            "issuer reference plan requires canonical serialization",
        )
    return plan


def load_release_market_reference_selection(
    manifest: DataReleaseManifestV1,
    *,
    snapshot: SourceSnapshotV1,
    policy: PolicyRecordV1 | None,
    admissions: tuple[SourceAdmissionV1, ...],
    artifacts: AdmissionArtifactReader,
) -> IssuerMarketReferenceSelectionV1 | None:
    """A release cannot supply its own country/industry classification authority.

    The effective deployment policy must pin the plan's content hash. This is
    explicit classification policy, distinct from automatic source admission.
    """
    plan = read_release_market_reference_plan(manifest, artifacts=artifacts)
    if plan is None:
        return None
    ref = next(
        ref for ref in manifest.artifact_refs if ref.role == MARKET_REFERENCE_PLAN_ROLE
    )
    if (
        policy is None
        or plan.policy_id != policy.policy_id
        or ref.content_hash not in policy.source_refs
    ):
        raise DataReleaseError(
            "MARKET_REFERENCE_PLAN_UNAPPROVED",
            "issuer reference plan must be pinned by the deployment policy",
        )
    if (
        plan.issuer_id != snapshot.identity.issuer_id
        or plan.valuation_at != snapshot.valuation_timestamp
    ):
        raise DataReleaseError(
            "MARKET_REFERENCE_PLAN_CONTEXT_MISMATCH",
            "issuer reference plan differs from the valuation issuer or timestamp",
        )
    if policy.issuer_id != plan.issuer_id:
        raise DataReleaseError(
            "MARKET_REFERENCE_POLICY_ISSUER_MISMATCH",
            "deployment policy must have the issuer reference plan scope",
        )
    selection = select_issuer_market_references(plan, admissions=admissions)
    if selection.status != "selected":
        raise DataReleaseError(
            "MARKET_REFERENCE_SELECTION_REFUSED",
            "issuer reference selection retains unresolved source requirements: "
            + ", ".join(selection.issue_codes),
        )
    return selection
