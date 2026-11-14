"""Original-bound conditional realized FCFF and prespecified scenario errors."""

from decimal import Decimal

from .annual_history import AnnualHistoryError
from .contracts import CanonicalFactV1, QualityStatus
from .numerical_policy import using_valuation_context
from .operating_label_contracts import (
    ConditionalOperatingLabelV1,
    OperatingComparisonRequestV1,
    OperatingScenarioComparisonV1,
    OperatingScenarioErrorV1,
)
from .operating_scenario_contracts import ScenarioPeriodInputsV1, scenario_policy_digest
from .operating_scenarios import (
    build_scenario_history,
    replay_operating_scenarios,
    resolve_scenario_observations,
)
from .serialization import sha256_digest
from .snapshots import SnapshotError
from .valuation_preparation import PreparationError, derive_historical_metrics


def _require_label_selection(request: OperatingComparisonRequestV1) -> None:
    decision, label = request.decision, request.label
    issuer = decision.source.identity.issuer_id
    base = decision.periods[-1]
    eligible = tuple(
        item
        for item in request.filing_inventory
        if (
            item.issuer_id == issuer
            and item.form == "10-K"
            and not item.is_amendment
            and item.available_at > decision.source.valuation_timestamp
            and item.period_end > base.period_end
        )
    )
    if not eligible:
        raise PreparationError(
            "LABEL_FIRST_ORIGINAL_UNAVAILABLE",
            "no subsequent original annual target in the pinned inventory",
        )
    first = eligible[0]
    if sum(item.available_at == first.available_at for item in eligible) != 1:
        raise PreparationError(
            "LABEL_FIRST_ORIGINAL_CONFLICT",
            "equally available first originals are ambiguous",
        )
    originals = label.source.originals
    if (
        len(originals) != 1
        or label.source.identity.issuer_id != issuer
        or originals[0].source.accession_number != first.accession_number
        or originals[0].source.available_at != first.available_at
        or originals[0].report_period_end != first.period_end
        or originals[0].source.is_amendment
        or label.source.valuation_timestamp != first.available_at
    ):
        raise PreparationError(
            "LABEL_FIRST_ORIGINAL_MISMATCH",
            "label must retain the first original even when incomplete",
        )
    prior, target = label.periods
    if (
        prior.period_start != base.period_start
        or prior.period_end != base.period_end
        or target.period_start.toordinal() != base.period_end.toordinal() + 1
        or target.period_end != first.period_end
        or target.fiscal_year != base.fiscal_year + 1
        or any(fact.accession_number != first.accession_number for fact in label.facts)
    ):
        raise PreparationError(
            "LABEL_TARGET_OR_BASIS_MISMATCH",
            "prior/target observations require one original and the first forecast horizon",
        )


@using_valuation_context
def replay_operating_comparison(
    request: OperatingComparisonRequestV1,
) -> OperatingScenarioComparisonV1:
    """Retain all model refusals; hypothetical outcomes never become ground truth."""
    forecasts = replay_operating_scenarios(request.decision)
    label_request = request.label
    selected: tuple[dict[str, CanonicalFactV1], ...] = ()
    source_error = None
    try:
        _require_label_selection(request)
        selected = resolve_scenario_observations(label_request, label_request.periods)
    except (PreparationError, SnapshotError, AnnualHistoryError) as error:
        source_error = error
    labels = []
    for scenario in label_request.scenarios:
        inputs: tuple[ScenarioPeriodInputsV1, ...] = ()
        metrics = None
        realized = None
        codes = ["LABEL_ASSUMPTIONS_UNREVIEWED", "HISTORY_THRESHOLD_UNVALIDATED"]
        missing: tuple[str, ...] = ()
        try:
            if source_error is not None:
                raise source_error
            prepared = build_scenario_history(
                label_request.periods,
                selected,
                scenario,
                policy_digest=scenario_policy_digest(),
                scope_evidence=label_request.scope_assumption_evidence_digests,
            )
            inputs = prepared.period_inputs
            metrics = derive_historical_metrics(
                prepared.history, estimated_inputs=prepared.estimates
            )
            values = tuple(
                item.value
                for item in metrics.metrics
                if item.metric_id == "realized_fcff"
                and item.fiscal_year == label_request.periods[-1].fiscal_year
            )
            if (
                metrics.quality_status is QualityStatus.ABSTAIN
                or metrics.missing_evidence
                or len(values) != 1
            ):
                raise PreparationError(
                    "LABEL_REALIZED_FCFF_UNAVAILABLE",
                    "shared metrics cannot derive this conditional outcome",
                    missing=metrics.missing_evidence,
                )
            realized = values[0]
        except (PreparationError, SnapshotError, AnnualHistoryError) as error:
            codes.append(error.code)
            missing = error.missing if isinstance(error, PreparationError) else ()
        labels.append(
            ConditionalOperatingLabelV1(
                scenario_id=scenario.scenario_id,
                status="provisional_conditional_label"
                if realized is not None
                else "abstained",
                target_period_start=label_request.periods[-1].period_start,
                target_period_end=label_request.periods[-1].period_end,
                accession_number=label_request.source.originals[
                    0
                ].source.accession_number,
                available_at=label_request.source.originals[0].source.available_at,
                period_inputs=inputs,
                historical_metrics=metrics,
                realized_fcff=realized,
                issue_codes=tuple(
                    dict.fromkeys((*codes, *(metrics.issue_codes if metrics else ())))
                ),
                missing_evidence=missing,
            )
        )
    label_assumptions = {item.scenario_id: item for item in label_request.scenarios}
    forecast_assumptions = {
        item.scenario_id: item for item in request.decision.scenarios
    }
    comparisons = []
    for forecast in forecasts.results:
        assumption = forecast_assumptions[forecast.scenario_id]
        paired = tuple(
            label
            for label in labels
            if (
                label_assumptions[label.scenario_id].operating_asset_fraction
                == assumption.operating_asset_fraction
                and label_assumptions[label.scenario_id].operating_liability_fraction
                == assumption.operating_liability_fraction
            )
        )
        for label in paired or (None,):
            codes = list(forecast.issue_codes)
            nodes = {item.node_id: item.value for item in forecast.nodes}
            predicted, base = nodes.get("fcff_1"), nodes.get("base_revenue")
            realized = label.realized_fcff if label is not None else None
            if label is None:
                codes.append("LABEL_PAIRED_ASSUMPTION_UNAVAILABLE")
            else:
                codes.extend(label.issue_codes)
            signed_error = None
            if (
                forecast.status == "provisional_scenario"
                and predicted is not None
                and realized is not None
                and base is not None
                and base > Decimal(0)
            ):
                signed_error = predicted - realized
            comparisons.append(
                OperatingScenarioErrorV1(
                    forecast_scenario_id=forecast.scenario_id,
                    label_scenario_id=label.scenario_id
                    if label is not None
                    else "unavailable",
                    model_id=forecast.model_id,
                    status="provisional_conditional_comparison"
                    if signed_error is not None
                    else "abstained",
                    forecast_fcff=predicted,
                    conditional_realized_fcff=realized,
                    signed_error=signed_error,
                    absolute_error=abs(signed_error)
                    if signed_error is not None
                    else None,
                    origin_base_revenue=base,
                    normalized_signed_error=signed_error / base
                    if signed_error is not None and base is not None
                    else None,
                    issue_codes=tuple(dict.fromkeys(codes)),
                )
            )
    result = OperatingScenarioComparisonV1(
        contract_version=(
            "fundamental.operating-comparison-replay.v2"
            if request.contract_version == "fundamental.operating-comparison.v2"
            else "fundamental.operating-comparison-replay.v1"
        ),
        input_digest=sha256_digest(request),
        output_digest="0" * 64,
        decision_input_digest=forecasts.input_digest,
        forecast_output_digest=forecasts.output_digest,
        label_input_digest=sha256_digest(label_request),
        label_policy_digest=request.policy_digest,
        retained_label_fact_ids=tuple(
            sorted(fact.fact_id for fact in label_request.facts)
        ),
        labels=tuple(labels),
        comparisons=tuple(comparisons),
    )
    return result.model_copy(
        update={
            "output_digest": sha256_digest(result.model_dump(exclude={"output_digest"}))
        }
    )
