"""Bind explicit forward hypotheses to eligible original annual observations."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from .annual_history import AnnualHistoryError, AnnualHistoryV1, resolve_annual_history
from .conditional_reinvestment_contracts import (
    CONDITIONAL_REINVESTMENT_POLICY,
    REINVESTMENT_CORE_FIELDS,
    ConditionalReinvestmentAssessmentV1,
    ConditionalReinvestmentPolicyV1,
    ConditionalReinvestmentRecipeV1,
    ReinvestmentObservationRefV1,
)
from .contracts import (
    CanonicalFactV1,
    PeriodType,
    QualityStatus,
    SourceRole,
    SourceSnapshotV1,
)
from .facts import canonical_fact_digest
from .serialization import canonical_bytes, sha256_digest
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    valuation_requirements_profile,
)


class ConditionalReinvestmentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def conditional_reinvestment_policy_digest() -> str:
    """Pin the installed assessor and its source/history validation dependencies."""

    root = Path(__file__).parent
    return sha256_digest(
        {
            "version": CONDITIONAL_REINVESTMENT_POLICY,
            "sources": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in (
                    "conditional_reinvestment.py",
                    "conditional_reinvestment_contracts.py",
                    "annual_history.py",
                    "valuation_requirements.py",
                    "original_issuer.py",
                    "contracts.py",
                    "facts.py",
                    "serialization.py",
                )
            },
        }
    )


def reinvestment_history_requirements_profile(
    model_id: str,
) -> ValuationRequirementsProfileV1:
    """Core source evidence only; not a registered valuation/release profile."""

    if model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_MODEL_INVALID", "unsupported forward model"
        )
    return ValuationRequirementsProfileV1(
        profile_id=f"{model_id}-{CONDITIONAL_REINVESTMENT_POLICY}-history",
        profile_version=CONDITIONAL_REINVESTMENT_POLICY,
        model_id=valuation_requirements_profile(model_id).model_id,
        annual_duration_fields=REINVESTMENT_CORE_FIELDS,
        annual_instant_fields=(),
        transition_filing_evidence_required=model_id == "transition_fcff_dcf",
    )


def bind_conditional_reinvestment_recipe(
    recipe: ConditionalReinvestmentRecipeV1,
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
) -> ConditionalReinvestmentAssessmentV1:
    """Resolve the shared history and reproduce its exact bound-policy assessment."""

    recipe = ConditionalReinvestmentRecipeV1.model_validate_json(
        canonical_bytes(recipe)
    )
    facts = tuple(facts)
    history, _ = _resolve_history(recipe, facts, snapshot)
    policy = ConditionalReinvestmentPolicyV1(
        recipe=recipe,
        policy_digest=conditional_reinvestment_policy_digest(),
        requirements_digest=reinvestment_history_requirements_profile(
            recipe.model_id
        ).digest,
        snapshot_manifest_digest=snapshot.manifest_digest,
        issuer_id=snapshot.identity.issuer_id,
        security_id=snapshot.identity.security_id,
        currency=snapshot.identity.currency,
        valuation_timestamp=snapshot.valuation_timestamp,
        observations=_observation_refs(history),
    )
    return assess_conditional_reinvestment(
        policy, facts, snapshot=snapshot, mapping_version=recipe.mapping_version
    )


def assess_conditional_reinvestment(
    policy: ConditionalReinvestmentPolicyV1,
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    mapping_version: str,
) -> ConditionalReinvestmentAssessmentV1:
    """Check immutable history/assumption bindings without valuing or approving."""

    policy = ConditionalReinvestmentPolicyV1.model_validate_json(
        canonical_bytes(policy)
    )
    if policy.policy_digest != conditional_reinvestment_policy_digest():
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_POLICY_MISMATCH", "executable policy differs"
        )
    if policy.recipe.mapping_version != mapping_version:
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_MAPPING_MISMATCH", "mapping version differs"
        )
    if (
        policy.snapshot_manifest_digest,
        policy.issuer_id,
        policy.security_id,
        policy.currency,
        policy.valuation_timestamp,
    ) != (
        snapshot.manifest_digest,
        snapshot.identity.issuer_id,
        snapshot.identity.security_id,
        snapshot.identity.currency,
        snapshot.valuation_timestamp,
    ):
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_SNAPSHOT_MISMATCH", "snapshot binding differs"
        )
    profile = reinvestment_history_requirements_profile(policy.recipe.model_id)
    if policy.requirements_digest != profile.digest:
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_REQUIREMENTS_MISMATCH", "history profile differs"
        )
    history, candidates = _resolve_history(policy.recipe, tuple(facts), snapshot)
    if policy.observations != _observation_refs(history):
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_OBSERVATIONS_MISMATCH",
            "hypotheses must bind every exact selected trailing core observation",
        )
    return ConditionalReinvestmentAssessmentV1(
        policy=policy,
        source_facts=tuple(
            sorted(
                (fact for period in history.periods for fact in period.duration_facts),
                key=lambda fact: fact.fact_id,
            )
        ),
        fiscal_years=tuple(period.fiscal_year for period in history.periods),
        input_digest=sha256_digest({"policy": policy, "candidate_facts": candidates}),
    )


def _observation_refs(
    history: AnnualHistoryV1,
) -> tuple[ReinvestmentObservationRefV1, ...]:
    return tuple(
        sorted(
            (
                ReinvestmentObservationRefV1(
                    fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact)
                )
                for period in history.periods
                for fact in period.duration_facts
            ),
            key=lambda item: item.fact_id,
        )
    )


def _resolve_history(
    recipe: ConditionalReinvestmentRecipeV1,
    facts: tuple[CanonicalFactV1, ...],
    snapshot: SourceSnapshotV1,
) -> tuple[AnnualHistoryV1, tuple[CanonicalFactV1, ...]]:
    try:
        snapshot = SourceSnapshotV1.model_validate_json(canonical_bytes(snapshot))
    except ValidationError as error:
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_SNAPSHOT_INVALID",
            "snapshot must reproduce its canonical manifest and source records",
        ) from error
    if len({fact.fact_id for fact in facts}) != len(facts):
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_FACT_CONFLICT", "duplicate fact identities"
        )
    candidates = tuple(
        sorted(
            (
                fact
                for fact in facts
                if fact.normalized_field in REINVESTMENT_CORE_FIELDS
            ),
            key=lambda fact: fact.fact_id,
        )
    )
    sources = {source.content_hash: source for source in snapshot.source_records}
    for fact in candidates:
        try:
            CanonicalFactV1.model_validate_json(canonical_bytes(fact))
        except ValidationError as error:
            raise ConditionalReinvestmentError(
                "CONDITIONAL_REINVESTMENT_SOURCE_INVALID",
                "core observation does not satisfy its canonical fact contract",
            ) from error
        source = sources.get(fact.source.content_hash)
        if (
            source is None
            or source.source_id != "sec-filing"
            or source.role is not SourceRole.FILING
            or source.form != "10-K"
            or source.is_amendment
            or source.available_at > snapshot.valuation_timestamp
            or fact.issuer_id != snapshot.identity.issuer_id
            or fact.security_id not in {None, snapshot.identity.security_id}
            or fact.quality is not QualityStatus.VERIFIED
            or fact.is_amendment
            or not fact.mapping_decision_id
            or not fact.accession_number
            or fact.accession_number != source.accession_number
            or fact.source.accession_number != source.accession_number
            or fact.source.source_url != source.uri
            or fact.source.source_role is not SourceRole.FILING
            or fact.available_at != source.available_at
            or fact.source.available_at != source.available_at
            or fact.period_end > snapshot.valuation_timestamp.date()
            or fact.period_start is None
            or fact.instant is not None
            or fact.context.period_type is not PeriodType.DURATION
            or fact.context.start_date != fact.period_start
            or fact.context.end_date != fact.period_end
            or fact.context.instant is not None
            or fact.context.concept_qname != fact.concept
            or fact.context.entity_scope.lstrip("0")
            != snapshot.identity.issuer_id.lstrip("0")
            or fact.context.dimensions
            or fact.context.consolidation_scope != "consolidated"
            or fact.currency != snapshot.identity.currency
            or fact.unit not in {fact.currency, f"iso4217:{fact.currency}"}
            or fact.context.unit_qname.replace("iso4217:", "") != fact.currency
            or not isinstance(fact.value, Decimal)
            or not fact.value.is_finite()
        ):
            raise ConditionalReinvestmentError(
                "CONDITIONAL_REINVESTMENT_SOURCE_INVALID",
                "core candidates require verified mapped original annual currency flows",
            )
    try:
        history = resolve_annual_history(
            candidates,
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
            profile=reinvestment_history_requirements_profile(recipe.model_id),
        )
    except AnnualHistoryError as error:
        raise ConditionalReinvestmentError(error.code, str(error)) from error
    if history.quality is QualityStatus.ABSTAIN:
        raise ConditionalReinvestmentError(
            "CONDITIONAL_REINVESTMENT_HISTORY_INCOMPLETE",
            "forward hypotheses require at least three consecutive complete core years",
        )
    for period in history.periods:
        if (
            len(
                {
                    (fact.source.content_hash, fact.accession_number)
                    for fact in period.duration_facts
                }
            )
            != 1
        ):
            raise ConditionalReinvestmentError(
                "CONDITIONAL_REINVESTMENT_ORIGINAL_MISMATCH",
                "each year's core flows must share one original",
            )
    return history, candidates
