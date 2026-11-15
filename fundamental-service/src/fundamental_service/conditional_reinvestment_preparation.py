"""Retain source and document binding outcomes before trusted release."""

from typing import Literal

from pydantic import Field, model_validator

from .command_artifacts import EvidenceArtifactStore
from .conditional_reinvestment import (
    ConditionalReinvestmentError,
    bind_conditional_reinvestment_recipe,
)
from .conditional_capital_balances import CapitalBalanceRole
from .conditional_reinvestment_contracts import (
    REINVESTMENT_CORE_FIELDS,
    ConditionalReinvestmentAssessmentV1,
    ConditionalReinvestmentPolicyV1,
    ConditionalReinvestmentRecipeV1,
)
from .conditional_reinvestment_release import (
    REINVESTMENT_ASSUMPTION_ROLE,
    validate_reinvestment_assumption_document,
)
from .contracts import CanonicalFactV1, SourceSnapshotV1, StrictModel
from .data_releases import ArtifactRefV1, DataReleaseError
from .facts import canonical_fact_digest
from .preparation_release import select_preparation_release_facts
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .valuation_requirements import (
    conditional_reinvestment_requirements_profile,
    select_released_facts,
)


class ConditionalReinvestmentBindingV1(StrictModel):
    protocol: Literal["conditional-reinvestment-binding-v1"] = (
        "conditional-reinvestment-binding-v1"
    )
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fact_digests: tuple[str, ...]
    assumption_document_ref: ArtifactRefV1 | None
    assessment: ConditionalReinvestmentAssessmentV1 | None
    issue_codes: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    failure_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def assessment_or_refusal(self) -> "ConditionalReinvestmentBindingV1":
        if (self.assessment is None) != bool(self.issue_codes):
            raise ValueError(
                "forward binding requires an assessment or explicit refusal"
            )
        if self.assessment is not None and (
            self.assumption_document_ref is None
            or self.missing_evidence
            or self.failure_reasons
        ):
            raise ValueError("forward assessment requires complete retained evidence")
        for items in (
            self.input_fact_digests,
            self.issue_codes,
            self.missing_evidence,
            self.failure_reasons,
        ):
            if items != tuple(sorted(set(items))):
                raise ValueError("forward binding evidence must be canonical")
        return self

    @property
    def policy(self) -> ConditionalReinvestmentPolicyV1 | None:
        return self.assessment.policy if self.assessment is not None else None

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def prepare_conditional_reinvestment(
    recipe: ConditionalReinvestmentRecipeV1,
    facts: tuple[CanonicalFactV1, ...],
    *,
    snapshot: SourceSnapshotV1,
    artifacts: EvidenceArtifactStore,
    conditional_capital: bool = False,
    hypothetical_balance_fields: tuple[CapitalBalanceRole, ...] = (),
) -> ConditionalReinvestmentBindingV1:
    """Use the owning source assessor and verify real assumption bytes on every call."""

    recipe = ConditionalReinvestmentRecipeV1.model_validate_json(
        canonical_bytes(recipe)
    )
    issues: set[str] = set()
    reasons: set[str] = set()
    missing: set[str] = set()
    reference = None
    try:
        artifact_id = recipe.assumption_document_uri.removeprefix("artifact://")
        if (
            not artifact_id
            or recipe.assumption_document_uri != f"artifact://{artifact_id}"
        ):
            raise DataReleaseError(
                "DATA_RELEASE_REINVESTMENT_DOCUMENT_UNBOUND",
                "deployment assumptions require an exact artifact URI",
            )
        record = artifacts.get(artifact_id)
        if record.status != "valid" or record.retention != "evidence":
            raise DataReleaseError(
                "DATA_RELEASE_REINVESTMENT_DOCUMENT_UNAVAILABLE",
                "assumptions must be retained valid evidence",
            )
        candidate = ArtifactRefV1(
            artifact_id=artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role=REINVESTMENT_ASSUMPTION_ROLE,
        )
        validate_reinvestment_assumption_document(
            recipe, (candidate,), artifacts=artifacts
        )
        reference = candidate
    except DataReleaseError as error:
        issues.add(error.code)
        reasons.add(str(error))
        missing.add("conditional_reinvestment_assumption_document")
    except Exception:
        issues.add("DATA_RELEASE_REINVESTMENT_DOCUMENT_UNAVAILABLE")
        reasons.add("retained deployment assumptions unavailable")
        missing.add("conditional_reinvestment_assumption_document")
    assessment = None
    try:
        # Check supplied core candidates before PIT selection can discard any.
        bind_conditional_reinvestment_recipe(recipe, facts, snapshot=snapshot)
        selected, _ = select_preparation_release_facts(facts, snapshot)
        requirements = select_released_facts(
            selected,
            profile=conditional_reinvestment_requirements_profile(
                recipe.model_id,
                conditional_capital=conditional_capital,
                hypothetical_balance_fields=hypothetical_balance_fields,
            ),
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
        )
        issues.update(requirements.issue_codes)
        missing.update(requirements.missing_fields)
        if requirements.missing_fields:
            reasons.add(
                "required observed source roles are missing: "
                + ",".join(requirements.missing_fields)
            )
        assessment = bind_conditional_reinvestment_recipe(
            recipe, selected, snapshot=snapshot
        )
    except (ConditionalReinvestmentError, SnapshotError) as error:
        issues.add(error.code)
        reasons.add(str(error))
        missing.update(
            set(REINVESTMENT_CORE_FIELDS) - {fact.normalized_field for fact in facts}
        )
    return ConditionalReinvestmentBindingV1(
        recipe_digest=recipe.digest,
        snapshot_manifest_digest=snapshot.manifest_digest,
        input_fact_digests=tuple(
            sorted({canonical_fact_digest(fact) for fact in facts})
        ),
        assumption_document_ref=reference,
        assessment=assessment if not issues else None,
        issue_codes=tuple(sorted(issues)),
        missing_evidence=tuple(sorted(missing)),
        failure_reasons=tuple(sorted(reasons)),
    )
