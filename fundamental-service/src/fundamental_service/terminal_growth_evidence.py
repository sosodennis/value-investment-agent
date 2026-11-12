"""Reproduce deployment-authorized terminal policy at the release boundary."""

from hashlib import sha256

from .contracts import SourceSnapshotV1
from .data_releases import DataReleaseError, DataReleaseManifestV1
from .market_source_selection import MarketSourceError
from .policies import PolicyRecordV1
from .serialization import canonical_bytes
from .source_admission import SourceAdmissionV1
from .source_admission_evidence import AdmissionArtifactReader
from .terminal_growth import (
    TerminalGrowthPlanV1,
    TerminalGrowthSelectionV1,
    select_terminal_growth,
    terminal_growth_evidence,
)

TERMINAL_GROWTH_PLAN_ROLE = "issuer_terminal_growth_plan"


def requires_terminal_growth_plan(policy: PolicyRecordV1 | None) -> bool:
    if policy is None or policy.market_inputs is None:
        return False
    evidence = next(
        x for x in policy.market_inputs.evidence if x.role == "terminal_growth"
    )
    return evidence.source_id.startswith("terminal-growth:") or (
        evidence.source_uri.startswith("urn:fundamental:terminal-growth:")
    )


def read_release_terminal_growth_plan(
    manifest: DataReleaseManifestV1, *, artifacts: AdmissionArtifactReader
) -> TerminalGrowthPlanV1 | None:
    refs = tuple(
        ref for ref in manifest.artifact_refs if ref.role == TERMINAL_GROWTH_PLAN_ROLE
    )
    if not refs:
        return None
    if len(refs) != 1:
        raise DataReleaseError(
            "TERMINAL_PLAN_AMBIGUOUS", "release requires one terminal-growth plan"
        )
    ref = refs[0]
    raw = artifacts.read(ref.artifact_id)
    if (
        ref.media_type != "application/json"
        or sha256(raw).hexdigest() != ref.content_hash
    ):
        raise DataReleaseError(
            "TERMINAL_PLAN_MISMATCH", "terminal plan differs from released bytes"
        )
    try:
        plan = TerminalGrowthPlanV1.model_validate_json(raw)
    except ValueError as error:
        raise DataReleaseError(
            "TERMINAL_PLAN_INVALID", "terminal-growth plan is invalid"
        ) from error
    if canonical_bytes(plan) != raw:
        raise DataReleaseError(
            "TERMINAL_PLAN_NONCANONICAL", "terminal plan is not canonical"
        )
    return plan


def load_release_terminal_growth_selection(
    manifest: DataReleaseManifestV1,
    *,
    snapshot: SourceSnapshotV1,
    policy: PolicyRecordV1 | None,
    admissions: tuple[SourceAdmissionV1, ...],
    artifacts: AdmissionArtifactReader,
) -> TerminalGrowthSelectionV1 | None:
    plan = read_release_terminal_growth_plan(manifest, artifacts=artifacts)
    if plan is None:
        if requires_terminal_growth_plan(policy):
            raise DataReleaseError(
                "TERMINAL_PLAN_MISSING",
                "source-derived terminal policy requires its released plan",
            )
        return None
    ref = next(x for x in manifest.artifact_refs if x.role == TERMINAL_GROWTH_PLAN_ROLE)
    if (
        policy is None
        or policy.market_inputs is None
        or ref.content_hash not in policy.source_refs
    ):
        raise DataReleaseError(
            "TERMINAL_PLAN_UNAPPROVED",
            "effective deployment market policy must authorize the terminal plan",
        )
    if (
        plan.policy_id != policy.policy_id
        or plan.issuer_id != snapshot.identity.issuer_id
        or plan.currency != snapshot.identity.currency
        or plan.valuation_at != snapshot.valuation_timestamp
    ):
        raise DataReleaseError(
            "TERMINAL_PLAN_CONTEXT_MISMATCH",
            "terminal plan differs from valuation issuer, currency, policy or time",
        )
    if policy.issuer_id != plan.issuer_id:
        raise DataReleaseError(
            "TERMINAL_PLAN_ISSUER_POLICY_MISMATCH",
            "deployment market policy must have the terminal plan issuer scope",
        )
    try:
        selection = select_terminal_growth(plan, admissions=admissions)
    except MarketSourceError as error:
        raise DataReleaseError(error.code, str(error)) from error
    evidence = next(
        x for x in policy.market_inputs.evidence if x.role == "terminal_growth"
    )
    rate_evidence = next(
        x for x in policy.market_inputs.evidence if x.role == "risk_free_rate"
    )
    if (
        policy.market_inputs.terminal_growth != selection.value
        or evidence != terminal_growth_evidence(selection)
        or policy.market_inputs.risk_free_rate != selection.risk_free_value
        or rate_evidence.method != "observed_source"
    ):
        raise DataReleaseError(
            "TERMINAL_POLICY_SOURCE_MISMATCH",
            "terminal-growth policy value or evidence differs from reproduced sources",
        )
    return selection
