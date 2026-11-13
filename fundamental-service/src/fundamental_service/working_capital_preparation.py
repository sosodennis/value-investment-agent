"""Bind explicit source-preparation recipes to canonical accounting evidence."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .contracts import CanonicalFactV1, InitialModelId, SourceSnapshotV1, StrictModel
from .policies import initial_model_specs
from .serialization import canonical_bytes, sha256_digest
from .valuation_requirements import composite_working_capital_requirements_profile
from .working_capital import (
    WORKING_CAPITAL_REQUIRED_EXCLUSIONS,
    CompositeWorkingCapitalAssessmentV1,
    CompositeWorkingCapitalInputV1,
    InclusionScenariosV1,
    ValuationWorkingCapitalPolicyV1,
    WorkingCapitalExclusionV1,
    assess_composite_working_capital,
    canonical_working_capital_inputs,
    working_capital_exclusion_coverage,
    working_capital_policy_digest,
)


class WorkingCapitalExclusionRecipeV1(StrictModel):
    account_class: str = Field(min_length=1)
    mapped_fact_role: str = Field(min_length=1)
    state: Literal["reported", "confirmed_absent"]
    rationale: str = Field(min_length=16)


class WorkingCapitalPeriodRecipeV1(StrictModel):
    accession_number: str = Field(min_length=1)
    period_end: date
    exclusions: tuple[WorkingCapitalExclusionRecipeV1, ...] = Field(min_length=1)
    asset_residual: InclusionScenariosV1
    liability_residual: InclusionScenariosV1
    perimeter_rationale: str = Field(min_length=16)

    @model_validator(mode="after")
    def explicit_perimeter(self) -> WorkingCapitalPeriodRecipeV1:
        keys = tuple(item.account_class for item in self.exclusions)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("recipe exclusions must be canonical and distinct")
        classes = [
            name
            for item in self.exclusions
            for name in working_capital_exclusion_coverage(item.mapped_fact_role)[1]
        ]
        if len(classes) != len(set(classes)) or set(classes) != set(
            WORKING_CAPITAL_REQUIRED_EXCLUSIONS
        ):
            raise ValueError("recipe exclusions must cover each required class once")
        if all(
            item.low == item.high
            for item in (self.asset_residual, self.liability_residual)
        ):
            raise ValueError("recipe residuals require explicit sensitivity")
        return self


class ValuationWorkingCapitalRecipeV1(StrictModel):
    protocol: Literal["valuation-working-capital-recipe-v1"] = (
        "valuation-working-capital-recipe-v1"
    )
    model_id: InitialModelId
    model_version: str = Field(min_length=1)
    requirements_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_version: str = Field(min_length=1)
    periods: tuple[WorkingCapitalPeriodRecipeV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def service_pins_and_periods(self) -> ValuationWorkingCapitalRecipeV1:
        profile = composite_working_capital_requirements_profile(
            self.model_id, operating_only=False
        )
        if self.requirements_profile_digest != profile.digest or not any(
            model.model_id == self.model_id
            and model.model_version == self.model_version
            for model in initial_model_specs()
        ):
            raise ValueError("recipe must pin the service model and requirements")
        periods = tuple(item.period_end for item in self.periods)
        if periods != tuple(sorted(set(periods))):
            raise ValueError("recipe annual periods must be canonical and distinct")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class WorkingCapitalBindingV1(StrictModel):
    protocol: Literal["working-capital-binding-v1"] = "working-capital-binding-v1"
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_facts: tuple[CanonicalFactV1, ...]
    assessments: tuple[CompositeWorkingCapitalAssessmentV1, ...]
    policy: ValuationWorkingCapitalPolicyV1 | None
    missing_evidence: tuple[str, ...]

    @model_validator(mode="after")
    def result_matches_assessments(self) -> WorkingCapitalBindingV1:
        if self.missing_evidence != tuple(sorted(set(self.missing_evidence))):
            raise ValueError("binding refusals must be canonical")
        if (self.policy is None) != bool(self.missing_evidence):
            raise ValueError("binding requires either a complete policy or refusals")
        if self.policy is not None and (
            not self.assessments
            or any(item.status != "estimated" for item in self.assessments)
            or self.policy.inputs
            != canonical_working_capital_inputs(
                tuple(item.policy_input for item in self.assessments)
            )
        ):
            raise ValueError("bound policy must match every successful assessment")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def bind_working_capital_recipe(
    recipe: ValuationWorkingCapitalRecipeV1,
    facts: tuple[CanonicalFactV1, ...],
    *,
    snapshot: SourceSnapshotV1,
) -> WorkingCapitalBindingV1:
    """Require unambiguous mapped observations, then use the existing assessor."""

    recipe = ValuationWorkingCapitalRecipeV1.model_validate_json(
        canonical_bytes(recipe)
    )
    candidates: dict[tuple[str, str], CanonicalFactV1] = {}
    missing: set[str] = set()
    assessments = []
    for period in recipe.periods:
        roles = (
            "current_assets",
            "current_liabilities",
            *(item.mapped_fact_role for item in period.exclusions),
        )
        selected: dict[str, CanonicalFactV1] = {}
        for role in roles:
            matches = tuple(
                fact
                for fact in facts
                if fact.normalized_field == role
                and fact.period_end == period.period_end
                and fact.accession_number == period.accession_number
            )
            for fact in matches:
                candidates[(fact.fact_id, sha256_digest(fact))] = fact
            if len(matches) != 1:
                reason = "MISSING" if not matches else "AMBIGUOUS"
                missing.add(
                    f"WORKING_CAPITAL_BINDING_{reason}:{period.period_end}:{period.accession_number}:{role}"
                )
            else:
                selected[role] = matches[0]
        if len(selected) != len(roles):
            continue
        exclusions = []
        for item in period.exclusions:
            side, classes = working_capital_exclusion_coverage(item.mapped_fact_role)
            parent = "current_assets" if side == "assets" else "current_liabilities"
            exclusions.append(
                WorkingCapitalExclusionV1(
                    **item.model_dump(),
                    side=side,
                    fact_id=selected[item.mapped_fact_role].fact_id,
                    covered_by_fact_id=selected[parent].fact_id,
                    covered_classes=classes,
                )
            )
        policy_input = CompositeWorkingCapitalInputV1(
            policy_digest=working_capital_policy_digest(),
            mapping_version=recipe.mapping_version,
            issuer_id=snapshot.identity.issuer_id,
            source_hash=selected["current_assets"].source.content_hash,
            current_assets_fact_id=selected["current_assets"].fact_id,
            current_liabilities_fact_id=selected["current_liabilities"].fact_id,
            **period.model_dump(exclude={"exclusions"}),
            exclusions=tuple(exclusions),
        )
        assessment = assess_composite_working_capital(
            policy_input, tuple(selected.values()), snapshot=snapshot
        )
        assessments.append(assessment)
        missing.update(assessment.missing_evidence)
    policy = None
    if not missing:
        policy = ValuationWorkingCapitalPolicyV1(
            **recipe.model_dump(exclude={"protocol", "periods"}),
            inputs=canonical_working_capital_inputs(
                tuple(item.policy_input for item in assessments)
            ),
        )
    return WorkingCapitalBindingV1(
        recipe_digest=recipe.digest,
        snapshot_manifest_digest=snapshot.manifest_digest,
        candidate_facts=tuple(candidates[key] for key in sorted(candidates)),
        assessments=tuple(assessments),
        policy=policy,
        missing_evidence=tuple(sorted(missing)),
    )
