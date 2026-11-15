"""Resolve explicit release input policies without changing composer arithmetic."""

from pydantic import ValidationError

from .contracts import CanonicalFactV1, SourceSnapshotV1
from .facts import canonical_fact_digest
from .conditional_capital_contracts import (
    ConditionalCapitalPolicyV1,
    ConditionalCapitalAssessmentV1,
)
from .conditional_capital import (
    ConditionalCapitalError,
    assess_conditional_capital,
)
from .data_releases import DataReleaseError, DataReleaseManifestV1
from .conditional_reinvestment_release import reinvestment_release_requirements
from .policies import initial_model_specs
from .serialization import canonical_bytes
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    composite_working_capital_requirements_profile,
    conditional_capital_requirements_profile,
    valuation_requirements_profile,
)
from .working_capital import (
    CompositeWorkingCapitalInputV1,
    ValuationWorkingCapitalPolicyV1,
)


def valuation_release_requirements(
    manifest: DataReleaseManifestV1, model_id: str
) -> ValuationRequirementsProfileV1:
    if manifest.conditional_reinvestment_policies:
        profile = reinvestment_release_requirements(manifest, model_id)
        if manifest.conditional_capital_policies:
            _conditional_release_policies(manifest)
        return profile
    profile = valuation_input_requirements(
        manifest.valuation_working_capital_policy, model_id
    )
    if manifest.conditional_capital_policies:
        policies = _conditional_release_policies(manifest)
        if any(policy.model_id != model_id for policy in policies):
            raise DataReleaseError(
                "DATA_RELEASE_CONDITIONAL_CAPITAL_MODEL_MISMATCH",
                "conditional capital requires the exact release model",
            )
        profile = conditional_capital_requirements_profile(
            model_id,
            composite_inputs=manifest.valuation_working_capital_policy is not None,
        )
    if (
        manifest.valuation_working_capital_policy is not None
        or manifest.conditional_capital_policies
    ) and set(manifest.required_fields) != set(profile.required_fact_fields):
        raise DataReleaseError(
            "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH",
            "composite valuation inputs require the exact service field profile",
        )
    return profile


def _conditional_release_policies(
    manifest: DataReleaseManifestV1,
) -> tuple[ConditionalCapitalPolicyV1, ...]:
    try:
        policies = tuple(
            ConditionalCapitalPolicyV1.model_validate_json(canonical_bytes(policy))
            for policy in manifest.conditional_capital_policies
        )
    except ValidationError as error:
        raise DataReleaseError(
            "DATA_RELEASE_CONDITIONAL_CAPITAL_INVALID",
            "conditional capital must satisfy its canonical policy contract",
        ) from error
    digests = tuple(policy.snapshot_manifest_digest for policy in policies)
    declared = {ref.manifest_digest: ref for ref in manifest.snapshot_refs}
    if (
        digests != tuple(sorted(set(digests)))
        or set(digests) != set(declared)
        or len(declared) != len(manifest.snapshot_refs)
    ):
        raise DataReleaseError(
            "DATA_RELEASE_CONDITIONAL_CAPITAL_UNBOUND",
            "conditional policies must cover every release snapshot exactly once in canonical order",
        )
    for policy in policies:
        facts = {
            ref.fact_id: ref.fact_digest
            for ref in declared[policy.snapshot_manifest_digest].facts
        }
        if any(
            facts.get(ref.fact_id) != ref.fact_digest
            for ref in (*policy.observations.values(), *policy.supporting_observations)
        ):
            raise DataReleaseError(
                "DATA_RELEASE_CONDITIONAL_CAPITAL_UNBOUND",
                "conditional observations require exact facts in their declared snapshot",
            )
        working = manifest.valuation_working_capital_policy
        if working is not None and (
            policy.model_id,
            policy.model_version,
            policy.mapping_version,
        ) != (working.model_id, working.model_version, working.mapping_version):
            raise DataReleaseError(
                "DATA_RELEASE_CONDITIONAL_CAPITAL_POLICY_MISMATCH",
                "conditional and working-capital inputs require one model and mapping version",
            )
    return policies


def valuation_release_conditional_capital(
    manifest: DataReleaseManifestV1,
    snapshot: SourceSnapshotV1,
    facts: tuple[CanonicalFactV1, ...],
    *,
    mapping_version: str,
) -> ConditionalCapitalAssessmentV1 | None:
    """Assess only immutable policies and facts declared by this release."""

    if not manifest.conditional_capital_policies:
        return None
    policies = _conditional_release_policies(manifest)
    policy = next(
        (
            item
            for item in policies
            if item.snapshot_manifest_digest == snapshot.manifest_digest
        ),
        None,
    )
    reference = next(
        (
            item
            for item in manifest.snapshot_refs
            if item.snapshot_id == snapshot.snapshot_id
        ),
        None,
    )
    if (
        policy is None
        or reference is None
        or reference.manifest_digest != snapshot.manifest_digest
    ):
        raise DataReleaseError(
            "DATA_RELEASE_CONDITIONAL_CAPITAL_UNBOUND",
            "conditional capital requires its exact declared security snapshot",
        )
    if {fact.fact_id: canonical_fact_digest(fact) for fact in facts} != {
        ref.fact_id: ref.fact_digest for ref in reference.facts
    }:
        raise DataReleaseError(
            "DATA_RELEASE_CONDITIONAL_CAPITAL_FACT_MISMATCH",
            "conditional capital requires the entire exact released fact set",
        )
    try:
        return assess_conditional_capital(
            policy, facts, snapshot=snapshot, mapping_version=mapping_version
        )
    except ConditionalCapitalError as error:
        raise DataReleaseError(error.code, str(error)) from error


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
