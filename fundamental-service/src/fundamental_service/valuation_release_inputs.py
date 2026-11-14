"""Resolve explicit release input policies without changing composer arithmetic."""

from pydantic import ValidationError

from .contracts import SourceSnapshotV1
from .data_releases import DataReleaseError, DataReleaseManifestV1
from .policies import initial_model_specs
from .serialization import canonical_bytes
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    composite_working_capital_requirements_profile,
    valuation_requirements_profile,
)
from .working_capital import (
    CompositeWorkingCapitalInputV1,
    ValuationWorkingCapitalPolicyV1,
)


def valuation_release_requirements(
    manifest: DataReleaseManifestV1, model_id: str
) -> ValuationRequirementsProfileV1:
    profile = valuation_input_requirements(
        manifest.valuation_working_capital_policy, model_id
    )
    if manifest.valuation_working_capital_policy is not None and set(
        manifest.required_fields
    ) != set(profile.required_fact_fields):
        raise DataReleaseError(
            "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH",
            "composite valuation inputs require the exact service field profile",
        )
    return profile


def valuation_input_requirements(
    policy: ValuationWorkingCapitalPolicyV1 | None, model_id: str
) -> ValuationRequirementsProfileV1:
    if policy is None:
        return valuation_requirements_profile(model_id)
    try:
        policy = ValuationWorkingCapitalPolicyV1.model_validate_json(
            canonical_bytes(policy)
        )
    except ValidationError as error:
        raise DataReleaseError(
            "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH",
            "composite valuation input policy must satisfy its canonical contract",
        ) from error
    if policy.model_id != model_id:
        raise DataReleaseError(
            "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH",
            "composite valuation inputs require the pinned service model",
        )
    profile = composite_working_capital_requirements_profile(
        model_id, operating_only=False
    )
    if policy.requirements_profile_digest != profile.digest or not any(
        model.model_id == model_id and model.model_version == policy.model_version
        for model in initial_model_specs()
    ):
        raise DataReleaseError(
            "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH",
            "composite valuation inputs require the exact service model and requirements",
        )
    return profile


def valuation_release_working_capital_inputs(
    manifest: DataReleaseManifestV1, snapshot: SourceSnapshotV1
) -> tuple[CompositeWorkingCapitalInputV1, ...]:
    """Select only inputs whose exact gross facts belong to this release view."""

    policy = manifest.valuation_working_capital_policy
    if policy is None:
        return ()
    declared = next(
        (
            {reference.fact_id for reference in item.facts}
            for item in manifest.snapshot_refs
            if item.snapshot_id == snapshot.snapshot_id
            and item.manifest_digest == snapshot.manifest_digest
        ),
        set(),
    )
    selected = tuple(
        item
        for item in policy.inputs
        if item.issuer_id == snapshot.identity.issuer_id
        and item.current_assets_fact_id in declared
    )
    if not selected or any(not set(item.fact_ids) <= declared for item in selected):
        raise DataReleaseError(
            "DATA_RELEASE_WORKING_CAPITAL_UNBOUND",
            "composite valuation inputs must bind the release snapshot and all supporting facts",
        )
    return selected
