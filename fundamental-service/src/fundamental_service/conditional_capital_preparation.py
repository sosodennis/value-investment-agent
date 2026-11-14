"""Bind deployment hypotheses to retained observations before trusted release."""

from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .conditional_capital import ConditionalCapitalError, assess_conditional_capital
from .conditional_capital_contracts import (
    CAPITAL_UNKNOWNS,
    OBSERVED_CAPITAL_FIELDS,
    CapitalObservationRefV1,
    ConditionalCapitalAssessmentV1,
    ConditionalCapitalPolicyV1,
    ConditionalCapitalRecipeV1,
)
from .contracts import CanonicalFactV1, SourceSnapshotV1, StrictModel
from .equity_dilution import AWARD_FACT_FIELDS
from .facts import canonical_fact_digest
from .serialization import canonical_bytes, sha256_digest


class ConditionalCapitalBindingV1(StrictModel):
    protocol: Literal["conditional-capital-binding-v1"] = (
        "conditional-capital-binding-v1"
    )
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fact_digests: tuple[str, ...]
    assessment: ConditionalCapitalAssessmentV1 | None
    issue_codes: tuple[str, ...]
    missing_evidence: tuple[str, ...]

    @model_validator(mode="after")
    def assessment_or_refusal(self) -> "ConditionalCapitalBindingV1":
        if (self.assessment is None) != bool(self.issue_codes):
            raise ValueError(
                "capital binding requires an assessment or explicit refusal"
            )
        if self.missing_evidence and self.assessment is not None:
            raise ValueError("missing capital observations cannot authorize hypotheses")
        for items in (self.input_fact_digests, self.issue_codes, self.missing_evidence):
            if items != tuple(sorted(set(items))):
                raise ValueError("capital binding evidence must be canonical")
        return self

    @property
    def policy(self) -> ConditionalCapitalPolicyV1 | None:
        return self.assessment.policy if self.assessment is not None else None

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def bind_conditional_capital_recipe(
    recipe: ConditionalCapitalRecipeV1,
    facts: tuple[CanonicalFactV1, ...],
    *,
    snapshot: SourceSnapshotV1,
) -> ConditionalCapitalBindingV1:
    """Select unambiguous latest balances, then apply the shared source assessor."""

    recipe = ConditionalCapitalRecipeV1.model_validate_json(canonical_bytes(recipe))
    issues: set[str] = set()
    missing: set[str] = set()
    selected: dict[str, CanonicalFactV1] = {}
    if len({fact.fact_id for fact in facts}) != len(facts):
        issues.add("CONDITIONAL_CAPITAL_FACT_CONFLICT")
    for role in OBSERVED_CAPITAL_FIELDS:
        candidates = tuple(fact for fact in facts if fact.normalized_field == role)
        instants = tuple(
            fact.instant for fact in candidates if fact.instant is not None
        )
        latest = max(instants) if instants else None
        matches = tuple(fact for fact in candidates if fact.instant == latest)
        if latest is None or not matches:
            missing.add(role)
            issues.add("CONDITIONAL_CAPITAL_BINDING_MISSING")
        elif len(matches) != 1:
            missing.add(role)
            issues.add("CONDITIONAL_CAPITAL_BINDING_AMBIGUOUS")
        else:
            selected[role] = matches[0]
    awards = tuple(fact for fact in facts if fact.normalized_field in AWARD_FACT_FIELDS)
    if not awards:
        missing.add("supporting_award_observations")
        issues.add("CONDITIONAL_CAPITAL_BINDING_MISSING")
    assessment = None
    if not issues:
        period = max(
            fact.period_end
            for role, fact in selected.items()
            if role != "common_shares_outstanding"
        )

        def reference(fact: CanonicalFactV1) -> CapitalObservationRefV1:
            return CapitalObservationRefV1(
                fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact)
            )

        try:
            if period > snapshot.valuation_timestamp.date():
                raise ConditionalCapitalError(
                    "CONDITIONAL_CAPITAL_SOURCE_INVALID",
                    "capital balance is in the future",
                )
            policy = ConditionalCapitalPolicyV1(
                **recipe.model_dump(exclude={"protocol"}),
                snapshot_manifest_digest=snapshot.manifest_digest,
                issuer_id=snapshot.identity.issuer_id,
                security_id=snapshot.identity.security_id,
                currency=snapshot.identity.currency,
                valuation_timestamp=snapshot.valuation_timestamp,
                period_end=period,
                observations={role: reference(fact) for role, fact in selected.items()},
                supporting_observations=tuple(reference(fact) for fact in awards),
                unknowns=CAPITAL_UNKNOWNS,
            )
            assessment = assess_conditional_capital(
                policy, facts, snapshot=snapshot, mapping_version=recipe.mapping_version
            )
        except ConditionalCapitalError as error:
            issues.add(error.code)
        except ValidationError:
            issues.add("CONDITIONAL_CAPITAL_BINDING_INVALID")
    return ConditionalCapitalBindingV1(
        recipe_digest=recipe.digest,
        snapshot_manifest_digest=snapshot.manifest_digest,
        input_fact_digests=tuple(
            sorted({canonical_fact_digest(fact) for fact in facts})
        ),
        assessment=assessment,
        issue_codes=tuple(sorted(issues)),
        missing_evidence=tuple(sorted(missing)),
    )
