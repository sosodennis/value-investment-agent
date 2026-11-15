"""Admit retained forward assumptions against the exact immutable release view."""

from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import ValidationError

from .conditional_reinvestment import (
    ConditionalReinvestmentError,
    assess_conditional_reinvestment,
)
from .conditional_reinvestment_contracts import (
    ConditionalReinvestmentAssessmentV1,
    ConditionalReinvestmentPolicyV1,
    ConditionalReinvestmentRecipeV1,
)
from .contracts import CanonicalFactV1, SourceSnapshotV1
from .data_releases import DataReleaseError, DataReleaseManifestV1
from .facts import canonical_fact_digest
from .serialization import canonical_bytes
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    conditional_reinvestment_requirements_profile,
)

REINVESTMENT_ASSUMPTION_ROLE = "conditional-reinvestment-assumptions-v1"


class ReinvestmentArtifactReader(Protocol):
    def read(self, artifact_id: str) -> bytes: ...


def reinvestment_assumption_document(recipe: ConditionalReinvestmentRecipeV1) -> bytes:
    """Canonical deployment document without its own circular URI/hash reference."""

    recipe = ConditionalReinvestmentRecipeV1.model_validate_json(
        canonical_bytes(recipe)
    )
    return canonical_bytes(
        recipe.model_dump(
            exclude={
                "protocol",
                "assumption_document_uri",
                "assumption_document_digest",
            }
        )
        | {"protocol": REINVESTMENT_ASSUMPTION_ROLE}
    )


def reinvestment_release_policies(
    manifest: DataReleaseManifestV1,
) -> tuple[ConditionalReinvestmentPolicyV1, ...]:
    try:
        policies = tuple(
            ConditionalReinvestmentPolicyV1.model_validate_json(canonical_bytes(policy))
            for policy in manifest.conditional_reinvestment_policies
        )
    except ValidationError as error:
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_INVALID", "invalid bound forward policy"
        ) from error
    digests = tuple(policy.snapshot_manifest_digest for policy in policies)
    declared = {ref.manifest_digest: ref for ref in manifest.snapshot_refs}
    if (
        digests != tuple(sorted(set(digests)))
        or set(digests) != set(declared)
        or len(declared) != len(manifest.snapshot_refs)
    ):
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_UNBOUND",
            "forward policies must cover each release snapshot exactly once in canonical order",
        )
    for policy in policies:
        facts = {
            ref.fact_id: ref.fact_digest
            for ref in declared[policy.snapshot_manifest_digest].facts
        }
        if any(
            facts.get(ref.fact_id) != ref.fact_digest for ref in policy.observations
        ):
            raise DataReleaseError(
                "DATA_RELEASE_REINVESTMENT_UNBOUND",
                "every forward observation must be an exact released fact",
            )
    return policies


def reinvestment_release_requirements(
    manifest: DataReleaseManifestV1, model_id: str
) -> ValuationRequirementsProfileV1:
    policies = reinvestment_release_policies(manifest)
    if manifest.valuation_working_capital_policy is not None:
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_POLICY_CONFLICT",
            "forward reinvestment cannot also claim a historical working-capital policy",
        )
    versions = {
        (
            policy.recipe.model_id,
            policy.recipe.model_version,
            policy.recipe.mapping_version,
        )
        for policy in policies
    }
    if len(versions) != 1 or any(version[0] != model_id for version in versions):
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_MODEL_MISMATCH",
            "forward inputs require one supported model/version and mapping",
        )
    if any(
        (policy.model_id, policy.model_version, policy.mapping_version) not in versions
        for policy in manifest.conditional_capital_policies
    ):
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_POLICY_CONFLICT",
            "capital and forward inputs must share one model/version and mapping",
        )
    profile = conditional_reinvestment_requirements_profile(
        model_id, conditional_capital=bool(manifest.conditional_capital_policies)
    )
    if set(manifest.required_fields) != set(profile.required_fact_fields):
        raise DataReleaseError(
            "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH",
            "forward inputs require the exact service-owned observed evidence profile",
        )
    return profile


def valuation_release_conditional_reinvestment(
    manifest: DataReleaseManifestV1,
    snapshot: SourceSnapshotV1,
    facts: tuple[CanonicalFactV1, ...],
    *,
    mapping_version: str,
    artifacts: ReinvestmentArtifactReader,
) -> ConditionalReinvestmentAssessmentV1 | None:
    """Verify document bytes and all source bindings; grant no release authority."""

    if not manifest.conditional_reinvestment_policies:
        return None
    policies = reinvestment_release_policies(manifest)
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
            ref
            for ref in manifest.snapshot_refs
            if ref.snapshot_id == snapshot.snapshot_id
        ),
        None,
    )
    if (
        policy is None
        or reference is None
        or reference.manifest_digest != snapshot.manifest_digest
    ):
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_UNBOUND",
            "forward policy requires its exact snapshot",
        )
    reinvestment_release_requirements(manifest, policy.recipe.model_id)
    if len({fact.fact_id for fact in facts}) != len(facts) or {
        fact.fact_id: canonical_fact_digest(fact) for fact in facts
    } != {ref.fact_id: ref.fact_digest for ref in reference.facts}:
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_FACT_MISMATCH",
            "forward assessment requires the entire exact released fact set",
        )
    recipe = policy.recipe
    refs = tuple(
        ref
        for ref in manifest.artifact_refs
        if recipe.assumption_document_uri == f"artifact://{ref.artifact_id}"
    )
    if len(refs) != 1 or (refs[0].role, refs[0].media_type, refs[0].content_hash) != (
        REINVESTMENT_ASSUMPTION_ROLE,
        "application/json",
        recipe.assumption_document_digest,
    ):
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_DOCUMENT_UNBOUND",
            "forward assumptions require one exact retained document identity, role and hash",
        )
    try:
        content = artifacts.read(refs[0].artifact_id)
    except Exception as error:
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_DOCUMENT_UNAVAILABLE",
            "assumption bytes unavailable",
        ) from error
    if hashlib.sha256(content).hexdigest() != recipe.assumption_document_digest:
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_DOCUMENT_HASH_MISMATCH",
            "assumption bytes differ",
        )
    if content != reinvestment_assumption_document(recipe):
        raise DataReleaseError(
            "DATA_RELEASE_REINVESTMENT_DOCUMENT_MISMATCH",
            "retained document must reproduce the exact versioned assumptions and limitations",
        )
    try:
        return assess_conditional_reinvestment(
            policy, facts, snapshot=snapshot, mapping_version=mapping_version
        )
    except ConditionalReinvestmentError as error:
        raise DataReleaseError(error.code, str(error)) from error
