"""Source-bound operating scenarios, separate from released point forecasts.

This research boundary accepts unreviewed observations, never approves their
mapping, and never publishes canonical facts or a data release. All hypothetical
accounting inputs stay distinct from the immutable reported facts.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from .annual_history import (
    AnnualHistoryError,
    AnnualHistoryPeriodV1,
    AnnualHistoryV1,
    EstimatedOperatingInputsV1,
    _select_period_fact,
)
from .contracts import (
    CalculationNodeV1,
    CanonicalFactV1,
    InitialModelId,
    QualityStatus,
    SourceRole,
)
from .facts import canonical_fact_digest
from .numerical_policy import using_valuation_context
from .operating_projection import (
    OperatingProjectionError,
    project_operating_nodes,
    resolve_operating_model,
)
from .operating_disclosures import conditional_transition_disclosures
from .original_issuer import (
    fact_matches_original_source,
    fact_matches_operating_identity,
)
from .serialization import canonical_bytes, sha256_digest
from .sec_rebuild import parsed_facts_to_candidates
from .snapshots import SnapshotError
from .valuation_preparation import (
    PreparationError,
    _transition_filing_evidence,
    compose_forecast_assumptions,
    derive_historical_metrics,
)
from .operating_scenario_contracts import (
    CORE_FIELDS,
    PARENT_CONCEPTS,
    SCENARIO_POLICY,
    BASELINE_SCENARIO_POLICY,
    BASELINE_SOURCE_POLICY,
    UnconsumedBaselineCapexV1,
    OperatingScenarioRequestV1,
    OperatingScenarioReplayV1,
    OperatingScenarioResultV1,
    OperatingScenarioV1,
    ParentPartitionV1,
    ScenarioPeriodInputsV1,
    ScenarioPeriodV1,
    ScenarioObservationSetV1,
)


def _latest_complete_original(
    request: ScenarioObservationSetV1, period: ScenarioPeriodV1, roles: set[str]
) -> str:
    source_roles: dict[tuple[datetime, str, str], set[str]] = {}
    for candidate in request.facts:
        if (
            candidate.period_end == period.period_end
            and candidate.normalized_field in roles
            and not candidate.context.dimensions
            and candidate.context.consolidation_scope == "consolidated"
        ):
            key = (
                candidate.available_at,
                candidate.source.content_hash,
                candidate.accession_number or "",
            )
            source_roles.setdefault(key, set()).add(candidate.normalized_field)
    complete_sources = tuple(
        key for key, observed in source_roles.items() if observed == roles
    )
    if not complete_sources:
        raise PreparationError(
            "SCENARIO_COMPLETE_ORIGINAL_MISSING",
            "period requires one original containing every selected observation",
        )
    newest = max(key[0] for key in complete_sources)
    latest = tuple(key for key in complete_sources if key[0] == newest)
    if len(latest) != 1:
        raise PreparationError(
            "SCENARIO_ORIGINAL_SELECTION_CONFLICT",
            "equally available complete originals are ambiguous",
        )
    return latest[0][1]


def _period_facts(
    request: ScenarioObservationSetV1, period: ScenarioPeriodV1
) -> dict[str, CanonicalFactV1]:
    facts = {fact.fact_id: fact for fact in request.facts}
    if len(facts) != len(request.facts):
        raise PreparationError("SCENARIO_FACT_ID_DUPLICATE", "duplicate input fact IDs")
    absent = tuple(sorted(set(period.fact_ids.values()) - facts.keys()))
    if absent:
        raise PreparationError(
            "SCENARIO_FACT_MISSING", "selected fact is absent", missing=absent
        )
    baseline = (
        period.unconsumed_capex is not None
        and request.source_selection_policy == BASELINE_SOURCE_POLICY
    )
    families = (
        (set(CORE_FIELDS), set(period.fact_ids) - set(CORE_FIELDS))
        if baseline
        else (set(period.fact_ids),)
    )
    source_hashes = {
        role: source_hash
        for family in families
        for source_hash in (_latest_complete_original(request, period, family),)
        for role in family
    }
    selected = {}
    for role, fact_id in sorted(period.fact_ids.items()):
        fact = facts.get(fact_id)
        if fact is None:
            raise PreparationError(
                "SCENARIO_FACT_MISSING", "selected fact is absent", missing=(fact_id,)
            )
        instant = role in {
            "current_assets",
            "current_liabilities",
            "cash_and_equivalents",
        }
        if (
            fact.normalized_field != role
            or not isinstance(fact.value, Decimal)
            or not fact.value.is_finite()
            or fact.currency != request.source.identity.currency
            or fact.unit not in {fact.currency, f"iso4217:{fact.currency}"}
            or fact.context.dimensions
            or fact.context.consolidation_scope != "consolidated"
            or fact.period_end != period.period_end
            or fact.period_start != (None if instant else period.period_start)
            or fact.instant != (period.period_end if instant else None)
            or fact.context.period_type.value != ("instant" if instant else "duration")
            or (role in PARENT_CONCEPTS and fact.concept != PARENT_CONCEPTS[role])
        ):
            raise PreparationError(
                "SCENARIO_ROLE_OR_PERIOD_INVALID",
                "source does not support the declared observation",
                missing=(fact_id,),
            )
        comparable = tuple(
            candidate
            for candidate in request.facts
            if candidate.normalized_field == role
            and candidate.source.content_hash == source_hashes[role]
            and candidate.period_end == period.period_end
            and not candidate.context.dimensions
            and candidate.context.consolidation_scope == "consolidated"
        )
        chosen = _select_period_fact(
            comparable,
            fiscal_year=period.fiscal_year,
            field=role,
            expected_instant=period.period_end if instant else None,
        )
        if chosen is None or chosen.fact_id != fact_id:
            raise PreparationError(
                "SCENARIO_SELECTION_POLICY_MISMATCH",
                "explicit period selection must reproduce the pinned source policy",
                missing=(fact_id,),
            )
        selected[role] = fact
    # Gross parents, cash and cash capex must belong to the same original.
    if (
        len(
            {
                (selected[role].source.content_hash, selected[role].accession_number)
                for role in PARENT_CONCEPTS
                if role in selected
            }
        )
        != 1
    ):
        raise PreparationError(
            "SCENARIO_PARENT_SOURCE_MISMATCH", "parent allocations require one original"
        )
    if period.unconsumed_capex is not None and (
        period.unconsumed_capex.source_content_hash != source_hashes["current_assets"]
    ):
        raise PreparationError(
            "SCENARIO_BASELINE_SOURCE_MISMATCH",
            "unknown capex evidence must refer to the selected original",
        )
    return selected


def _validate_sources(request: ScenarioObservationSetV1) -> None:
    mappings = {mapping.decision_id: mapping for mapping in request.mappings}
    reproduced: dict[tuple[str, str], set[str]] = {}
    for fact in request.facts:
        if (
            not fact_matches_original_source(fact, request.source)
            or not fact_matches_operating_identity(fact, request.source)
            or fact.source.source_role is not SourceRole.FILING
            or fact.is_amendment
            or fact.available_at > request.source.valuation_timestamp
            or fact.period_end > request.source.valuation_timestamp.date()
            or fact.quality not in {QualityStatus.PROVISIONAL, QualityStatus.VERIFIED}
        ):
            raise PreparationError(
                "SCENARIO_ORIGINAL_SOURCE_INVALID",
                "all retained decision observations must match an available original",
                missing=(fact.fact_id,),
            )
        mapping = mappings.get(fact.mapping_decision_id or "")
        if mapping is None:
            raise PreparationError(
                "SCENARIO_MAPPING_MISSING",
                "fact requires its exact mapping proposal",
                missing=(fact.fact_id,),
            )
        key = (fact.source.content_hash, mapping.decision_id)
        if key not in reproduced:
            original = next(
                original
                for original in request.source.originals
                if original.source.content_hash == fact.source.content_hash
            )
            candidates = parsed_facts_to_candidates(
                original.report,
                source=original.source,
                issuer_id=request.source.identity.issuer_id,
                normalized_field=mapping.normalized_field,
                mapping=mapping,
            )
            # Reproduce reported values and computed-role evidence through the
            # shared mapper, without asserting review or promoting quality.
            reproduced[key] = {
                canonical_fact_digest(candidate.canonical_fact(quality=quality))
                for candidate in candidates
                for quality in (QualityStatus.PROVISIONAL, QualityStatus.VERIFIED)
            }
        if canonical_fact_digest(fact) not in reproduced[key]:
            raise PreparationError(
                "SCENARIO_ORIGINAL_FACT_MISMATCH",
                "fact does not reproduce from its pinned original and mapping",
                missing=(fact.fact_id,),
            )


def _partition(
    parent: CanonicalFactV1,
    fraction: Decimal,
    *,
    excluded: CanonicalFactV1 | None = None,
) -> ParentPartitionV1:
    assert isinstance(parent.value, Decimal)
    known = excluded.value if excluded is not None else Decimal(0)
    assert isinstance(known, Decimal)
    residual = parent.value - known
    if min(parent.value, known, residual) < 0:
        raise PreparationError(
            "SCENARIO_PARENT_INFEASIBLE",
            "reported parent cannot support the nonnegative partition",
        )
    operating = residual * fraction
    return ParentPartitionV1(
        parent_fact_id=parent.fact_id,
        parent_value=parent.value,
        known_exclusion_fact_ids=(excluded.fact_id,) if excluded is not None else (),
        known_excluded=known,
        operating=operating,
        unresolved_excluded=residual - operating,
    )


@dataclass(frozen=True)
class ScenarioHistory:
    history: AnnualHistoryV1
    estimates: tuple[EstimatedOperatingInputsV1, ...]
    period_inputs: tuple[ScenarioPeriodInputsV1, ...]


def resolve_scenario_observations(
    observations: ScenarioObservationSetV1, periods: tuple[ScenarioPeriodV1, ...]
) -> tuple[dict[str, CanonicalFactV1], ...]:
    """Reproduce and select original observations before any hypothetical allocation."""
    if any(period.unconsumed_capex is not None for period in periods):
        try:
            if (
                not isinstance(observations, OperatingScenarioRequestV1)
                or periods != observations.periods
            ):
                raise ValueError("unknown capex is decision-baseline only")
            OperatingScenarioRequestV1.model_validate_json(
                canonical_bytes(observations)
            )
        except (ValidationError, ValueError) as error:
            raise PreparationError(
                "SCENARIO_BASELINE_POLICY_INVALID", str(error)
            ) from error
    _validate_sources(observations)
    return tuple(_period_facts(observations, period) for period in periods)


@using_valuation_context
def build_scenario_history(
    periods: tuple[ScenarioPeriodV1, ...],
    selected_periods: tuple[dict[str, CanonicalFactV1], ...],
    scenario: OperatingScenarioV1,
    *,
    policy_digest: str,
    scope_evidence: tuple[str, ...],
    policy_version: str = SCENARIO_POLICY,
) -> ScenarioHistory:
    """Allocate the same source parents for forecasts and conditional outcomes."""
    inputs: list[ScenarioPeriodInputsV1] = []
    estimates: list[EstimatedOperatingInputsV1] = []
    annual_periods: list[AnnualHistoryPeriodV1] = []
    for period, facts in zip(periods, selected_periods, strict=True):
        assets = _partition(
            facts["current_assets"],
            scenario.operating_asset_fraction,
            excluded=facts["cash_and_equivalents"],
        )
        liabilities = _partition(
            facts["current_liabilities"],
            scenario.operating_liability_fraction,
        )
        capex: ParentPartitionV1 | UnconsumedBaselineCapexV1 = (
            period.unconsumed_capex
            if period.unconsumed_capex is not None
            else _partition(
                facts["capital_expenditure"],
                scenario.continuing_capex_fractions[period.fiscal_year],
            )
        )
        assumption_digest = sha256_digest(
            {
                "scenario": scenario,
                "period": period,
                "policy": policy_digest,
                "scope_evidence": scope_evidence,
            }
        )
        inputs.append(
            ScenarioPeriodInputsV1(
                fiscal_year=period.fiscal_year,
                assets=assets,
                liabilities=liabilities,
                capex=capex,
                operating_working_capital=assets.operating - liabilities.operating,
                assumption_digest=assumption_digest,
            )
        )
        estimates.append(
            EstimatedOperatingInputsV1(
                fiscal_year=period.fiscal_year,
                capital_expenditure=(
                    capex.operating if isinstance(capex, ParentPartitionV1) else capex
                ),
                operating_working_capital=inputs[-1].operating_working_capital,
                capex_facts=(
                    (facts["capital_expenditure"],)
                    if isinstance(capex, ParentPartitionV1)
                    else ()
                ),
                working_capital_facts=tuple(
                    facts[role]
                    for role in (
                        "current_assets",
                        "cash_and_equivalents",
                        "current_liabilities",
                    )
                ),
                assumption_digest=assumption_digest,
            )
        )
        annual_periods.append(
            AnnualHistoryPeriodV1(
                fiscal_year=period.fiscal_year,
                period_start=period.period_start,
                period_end=period.period_end,
                duration_facts=tuple(facts[role] for role in CORE_FIELDS),
                instant_facts=(),
            )
        )
    history = AnnualHistoryV1(
        requirements_profile_id=policy_version,
        requirements_profile_digest=policy_digest,
        requested_fiscal_years=tuple(
            period.fiscal_year for period in reversed(periods)
        ),
        periods=tuple(annual_periods),
        missing_fields=(),
        quality=QualityStatus.PROVISIONAL,
        issue_codes=(
            "SCENARIO_ASSUMPTIONS_UNREVIEWED",
            "HISTORY_THRESHOLD_UNVALIDATED",
        ),
    )
    return ScenarioHistory(history, tuple(estimates), tuple(inputs))


@using_valuation_context
def replay_operating_scenarios(
    request: OperatingScenarioRequestV1,
) -> OperatingScenarioReplayV1:
    """Evaluate every scenario with #352; hypothetical values stay research-only."""
    models: tuple[InitialModelId, ...] = ("fcff_dcf", "transition_fcff_dcf")
    if set(request.model_versions) != set(models):
        raise ValueError("both formal model versions must be pinned")
    model_specs = {
        model_id: resolve_operating_model(model_id, request.model_versions[model_id])
        for model_id in models
    }
    request = request.model_copy(
        update={
            "facts": tuple(
                sorted(
                    request.facts, key=lambda fact: (fact.fact_id, sha256_digest(fact))
                )
            )
        }
    )
    source_error = None
    selected_periods = []
    try:
        selected_periods = list(resolve_scenario_observations(request, request.periods))
    except (PreparationError, SnapshotError, AnnualHistoryError) as error:
        source_error = error
    disclosure_error = None
    disclosure_fact_ids: tuple[str, ...] = ()
    if source_error is None and request.transition_disclosures is not None:
        try:
            disclosures = conditional_transition_disclosures(
                request.transition_disclosures,
                facts=request.facts,
                mappings=request.mappings,
                source=request.source,
                period_start=request.periods[-1].period_start,
                period_end=request.periods[-1].period_end,
            )
            disclosure_fact_ids = tuple(fact.fact_id for fact in disclosures)
        except SnapshotError as error:
            disclosure_error = error
    results = []
    for scenario in request.scenarios:
        for model_id in models:
            transition_fact_ids: tuple[str, ...] = ()
            inputs: list[ScenarioPeriodInputsV1] = []
            metrics = None
            forecast = None
            tax = None
            nodes: tuple[CalculationNodeV1, ...] = ()
            codes = ["SCENARIO_ASSUMPTIONS_UNREVIEWED", "HISTORY_THRESHOLD_UNVALIDATED"]
            missing: tuple[str, ...] = ()
            try:
                if source_error is not None:
                    raise source_error
                prepared = build_scenario_history(
                    request.periods,
                    tuple(selected_periods),
                    scenario,
                    policy_digest=request.policy_digest,
                    policy_version=request.policy_version,
                    scope_evidence=request.scope_assumption_evidence_digests,
                )
                inputs = list(prepared.period_inputs)
                if model_id == "transition_fcff_dcf":
                    if request.transition_disclosures is None:
                        _transition_filing_evidence(
                            request.facts, snapshot=request.source
                        )
                    else:
                        if disclosure_error is not None:
                            raise disclosure_error
                        codes.extend(
                            (
                                "TRANSITION_DISCLOSURES_UNREVIEWED",
                                "MODEL_SUITABILITY_UNESTABLISHED",
                            )
                        )
                        transition_fact_ids = disclosure_fact_ids
                history = prepared.history
                metrics = derive_historical_metrics(
                    history, estimated_inputs=prepared.estimates
                )
                if (
                    metrics.quality_status is QualityStatus.ABSTAIN
                    or metrics.missing_evidence
                ):
                    raise PreparationError(
                        "SCENARIO_METRICS_UNAVAILABLE",
                        "scenario metrics failed their shared numeric gates",
                        missing=metrics.missing_evidence,
                    )
                forecast = compose_forecast_assumptions(history, metrics)
                rates = tuple(
                    metric.value
                    for metric in metrics.metrics
                    if metric.metric_id == "normalized_tax_rate"
                )
                tax = sum(rates, Decimal(0)) / Decimal(len(rates))
                nodes = project_operating_nodes(
                    forecast,
                    tax_rate=tax,
                    historical_fact_ids=tuple(
                        sorted(
                            {
                                *transition_fact_ids,
                                *(
                                    fact_id
                                    for period in request.periods
                                    for fact_id in period.fact_ids.values()
                                ),
                            }
                        )
                    ),
                )
            except (
                PreparationError,
                OperatingProjectionError,
                SnapshotError,
                AnnualHistoryError,
            ) as error:
                codes.append(error.code)
                missing = error.missing if isinstance(error, PreparationError) else ()
                forecast, tax, nodes = None, None, ()
            results.append(
                OperatingScenarioResultV1(
                    scenario_id=scenario.scenario_id,
                    model_id=model_id,
                    model_version=model_specs[model_id].model_version,
                    model_spec_digest=sha256_digest(model_specs[model_id]),
                    status="provisional_scenario" if nodes else "abstained",
                    issue_codes=tuple(
                        dict.fromkeys(
                            (*codes, *(metrics.issue_codes if metrics else ()))
                        )
                    ),
                    missing_evidence=missing,
                    period_inputs=tuple(inputs),
                    historical_metrics=metrics,
                    forecast=forecast,
                    tax_rate=tax,
                    nodes=nodes,
                )
            )
    result = OperatingScenarioReplayV1(
        contract_version=(
            "fundamental.operating-scenario-replay.v3"
            if request.policy_version == BASELINE_SCENARIO_POLICY
            else "fundamental.operating-scenario-replay.v2"
        ),
        input_digest=sha256_digest(request),
        output_digest="0" * 64,
        retained_fact_ids=tuple(sorted(fact.fact_id for fact in request.facts)),
        results=tuple(results),
    )
    return result.model_copy(
        update={
            "output_digest": sha256_digest(result.model_dump(exclude={"output_digest"}))
        }
    )
