"""Internal operating-target preparation; this does not authorize a valuation.

Like the low-level valuation composer, this accepts evidence already checked
by its caller. A supplied release reference is not release authentication or
mapping approval. Empirical replay must still use the verified release path.
"""

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .annual_history import AnnualHistoryError, resolve_annual_history
from .contracts import (
    CalculationNodeV1,
    CanonicalFactV1,
    ForecastAssumptionsV1,
    QualityStatus,
    SourceRole,
    SourceSnapshotV1,
    StrictModel,
)
from .numerical_policy import VALUATION_NUMERICAL_POLICY, using_valuation_context
from .original_issuer import IssuerOperatingSourceV1
from .operating_projection import (
    OperatingProjectionError,
    project_operating_nodes,
    resolve_operating_model,
)
from .serialization import sha256_digest
from .valuation_preparation import (
    FORECAST_COMPOSER_VERSION,
    HistoricalMetricsV1,
    PreparationError,
    _transition_filing_evidence,
    compose_forecast_assumptions,
    derive_historical_metrics,
)
from .valuation_requirements import (
    composite_working_capital_requirements_profile,
    operating_forecast_requirements_profile,
    select_released_facts,
)
from .working_capital import (
    CompositeWorkingCapitalInputV1,
    canonical_working_capital_inputs,
)

HISTORY_WINDOW_POLICY: Literal["complete-trailing-annual-v1"] = (
    "complete-trailing-annual-v1"
)


class OperatingForecastV1(StrictModel):
    """Provisional operating targets with complete input and metric lineage."""

    contract_version: Literal["fundamental.operating-forecast.v1"] = (
        "fundamental.operating-forecast.v1"
    )
    scope: Literal["operating_targets_only"] = "operating_targets_only"
    composer_version: str = FORECAST_COMPOSER_VERSION
    numerical_policy_version: str = VALUATION_NUMERICAL_POLICY
    status: Literal["prepared", "abstained"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_release_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(min_length=1)
    quality_status: QualityStatus
    supported_history_threshold: None = None
    issue_codes: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    selected_fact_ids: tuple[str, ...]
    rejected_fact_ids: tuple[str, ...]
    fiscal_years: tuple[int, ...]
    history_window_years: Literal[3, 4, 5] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    history_window_policy: Literal["complete-trailing-annual-v1"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    excluded_history_fact_ids: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    historical_metrics: HistoricalMetricsV1
    forecast: ForecastAssumptionsV1 | None
    tax_rate: Decimal | None
    nodes: tuple[CalculationNodeV1, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def disposition_matches_targets(self) -> "OperatingForecastV1":
        prepared = self.status == "prepared"
        if prepared != (
            self.forecast is not None and self.tax_rate is not None and bool(self.nodes)
        ):
            raise ValueError("prepared operating targets must be complete")
        if not prepared and (
            self.forecast is not None or self.tax_rate is not None or self.nodes
        ):
            raise ValueError("abstained operating forecasts cannot contain targets")
        if self.quality_status is not (
            QualityStatus.PROVISIONAL if prepared else QualityStatus.ABSTAIN
        ):
            raise ValueError("operating disposition must retain provisional quality")
        if (self.history_window_years is None) != (self.history_window_policy is None):
            raise ValueError("explicit history windows require their policy version")
        if (
            prepared
            and self.history_window_years is not None
            and (len(self.fiscal_years) != self.history_window_years)
        ):
            raise ValueError("prepared forecasts must use the exact requested history")
        if self.excluded_history_fact_ids != tuple(
            sorted(set(self.excluded_history_fact_ids) - set(self.selected_fact_ids))
        ):
            raise ValueError(
                "excluded history facts must be distinct from selected facts"
            )
        return self


@using_valuation_context
def prepare_operating_forecast(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"],
    model_version: str,
    policy_id: str,
    policy_version: str,
    mapping_version: str,
    data_release_manifest_digest: str,
    history_window_years: Literal[3, 4, 5] | None = None,
    working_capital_inputs: tuple[CompositeWorkingCapitalInputV1, ...] = (),
) -> OperatingForecastV1:
    """Compose the formal operating stage from already released canonical facts.

    All supplied facts, including rejected inputs, bind input identity. This
    function performs no I/O, release verification, signing or quality promotion.
    """

    resolve_operating_model(model_id, model_version)
    if history_window_years is not None and (
        not isinstance(history_window_years, int)
        or history_window_years not in (3, 4, 5)
    ):
        raise ValueError("explicit operating history must be three, four or five years")
    return _prepare(
        tuple(facts),
        snapshot=snapshot,
        model_id=model_id,
        model_version=model_version,
        policy_id=policy_id,
        policy_version=policy_version,
        mapping_version=mapping_version,
        data_release_manifest_digest=data_release_manifest_digest,
        history_window_years=history_window_years,
        working_capital_inputs=canonical_working_capital_inputs(working_capital_inputs),
    )


def _prepare(
    facts: tuple[CanonicalFactV1, ...],
    *,
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"],
    model_version: str,
    policy_id: str,
    policy_version: str,
    mapping_version: str,
    data_release_manifest_digest: str,
    history_window_years: Literal[3, 4, 5] | None,
    working_capital_inputs: tuple[CompositeWorkingCapitalInputV1, ...],
) -> OperatingForecastV1:
    profile = (
        composite_working_capital_requirements_profile(model_id)
        if working_capital_inputs
        else operating_forecast_requirements_profile(model_id)
    )
    selected = select_released_facts(
        facts,
        profile=profile,
        snapshot=snapshot,
        valuation_timestamp=snapshot.valuation_timestamp,
        additional_fact_ids=tuple(
            fact_id for item in working_capital_inputs for fact_id in item.fact_ids
        ),
    )
    input_digest = sha256_digest(
        {
            "contract_version": "fundamental.operating-forecast.v1",
            "composer_version": FORECAST_COMPOSER_VERSION,
            "numerical_policy_version": VALUATION_NUMERICAL_POLICY,
            "facts": sorted(
                facts, key=lambda fact: (fact.fact_id, sha256_digest(fact))
            ),
            "snapshot": snapshot,
            "profile": profile,
            "model_version": model_version,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "mapping_version": mapping_version,
            "data_release_manifest_digest": data_release_manifest_digest,
            **(
                {"working_capital_inputs": working_capital_inputs}
                if working_capital_inputs
                else {}
            ),
            **(
                {
                    "history_window_years": history_window_years,
                    "history_window_policy": HISTORY_WINDOW_POLICY,
                }
                if history_window_years is not None
                else {}
            ),
        }
    )
    metrics = HistoricalMetricsV1(
        profile_id=profile.profile_id,
        profile_digest=profile.digest,
        quality_status=QualityStatus.ABSTAIN,
        issue_codes=selected.issue_codes,
        missing_evidence=selected.missing_fields,
        working_capital_inputs=working_capital_inputs,
    )
    fiscal_years: tuple[int, ...] = ()
    selected_fact_ids = tuple(fact.fact_id for fact in selected.facts)
    excluded_history_fact_ids: tuple[str, ...] = ()
    forecast = None
    tax_rate = None
    nodes: tuple[CalculationNodeV1, ...] = ()
    if not selected.missing_fields:
        try:
            if any(
                item.mapping_version != mapping_version
                for item in working_capital_inputs
            ):
                raise PreparationError(
                    "WORKING_CAPITAL_MAPPING_VERSION_MISMATCH",
                    "composite inputs must pin the released mapping version",
                )
            if len({fact.fact_id for fact in facts}) != len(facts):
                raise PreparationError(
                    "OPERATING_FACT_ID_DUPLICATE", "input fact IDs must be unique"
                )
            for fact in selected.facts:
                if fact.fact_id in {
                    fact_id
                    for item in working_capital_inputs
                    for fact_id in item.fact_ids
                }:
                    continue
                if isinstance(snapshot, IssuerOperatingSourceV1):
                    source = next(
                        source
                        for source in snapshot.source_records
                        if source.content_hash == fact.source.content_hash
                    )
                    if (
                        fact.accession_number != source.accession_number
                        or fact.source.accession_number != source.accession_number
                        or fact.source.source_url != source.uri
                        or fact.source.source_role is not SourceRole.FILING
                        or fact.source.available_at != source.available_at
                        or fact.available_at != source.available_at
                        or fact.is_amendment
                    ):
                        raise PreparationError(
                            "OPERATING_ORIGINAL_SOURCE_MISMATCH",
                            "issuer operating facts require their exact original source",
                            missing=(fact.fact_id,),
                        )
                if fact.normalized_field == "filed_operating_evidence":
                    continue
                currency = snapshot.identity.currency
                if fact.currency != currency or fact.unit not in {
                    currency,
                    f"iso4217:{currency}",
                }:
                    raise PreparationError(
                        "OPERATING_FACT_UNIT_INVALID",
                        "operating monetary roles require the issuer currency unit",
                        missing=(fact.fact_id,),
                    )
                if fact.source.available_at > snapshot.valuation_timestamp:
                    raise PreparationError(
                        "OPERATING_SOURCE_NOT_AVAILABLE",
                        "fact source was unavailable at the decision timestamp",
                        missing=(fact.fact_id,),
                    )
            if profile.transition_filing_evidence_required:
                _transition_filing_evidence(selected.facts, snapshot=snapshot)
            history = resolve_annual_history(
                selected.facts,
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                profile=profile,
                working_capital_inputs=working_capital_inputs,
            )
            fiscal_years = tuple(period.fiscal_year for period in history.periods)
            if history_window_years is not None:
                if len(history.periods) < history_window_years:
                    raise PreparationError(
                        "OPERATING_HISTORY_WINDOW_UNAVAILABLE",
                        "the exact requested trailing history is incomplete",
                        missing=tuple(
                            f"{year}:{field}"
                            for year, field in history.missing_fields
                            if year
                            in history.requested_fiscal_years[:history_window_years]
                        ),
                    )
                history = replace(
                    history, periods=history.periods[-history_window_years:]
                )
                fiscal_years = tuple(period.fiscal_year for period in history.periods)
                used = {
                    fact.fact_id
                    for period in history.periods
                    for fact in (*period.duration_facts, *period.instant_facts)
                }
                used.update(
                    fact.fact_id
                    for fact in selected.facts
                    if fact.normalized_field == "filed_operating_evidence"
                )
                selected_fact_ids = tuple(sorted(used))
                excluded_history_fact_ids = tuple(
                    sorted({fact.fact_id for fact in selected.facts} - used)
                )
            metrics = derive_historical_metrics(history)
            if working_capital_inputs:
                metrics = metrics.model_copy(
                    update={"working_capital_inputs": working_capital_inputs}
                )
            if metrics.quality_status is not QualityStatus.ABSTAIN:
                forecast = compose_forecast_assumptions(history, metrics)
                taxes = tuple(
                    metric.value
                    for metric in metrics.metrics
                    if metric.metric_id == "normalized_tax_rate"
                )
                tax_rate = sum(taxes, Decimal("0")) / Decimal(len(taxes))
                nodes = project_operating_nodes(
                    forecast,
                    tax_rate=tax_rate,
                    historical_fact_ids=selected_fact_ids,
                )
        except (
            PreparationError,
            AnnualHistoryError,
            OperatingProjectionError,
        ) as error:
            metrics = metrics.model_copy(
                update={
                    "quality_status": QualityStatus.ABSTAIN,
                    "issue_codes": (*metrics.issue_codes, error.code),
                    "missing_evidence": (
                        *metrics.missing_evidence,
                        *(error.missing if isinstance(error, PreparationError) else ()),
                    ),
                }
            )
            forecast, tax_rate, nodes = None, None, ()
    prepared = forecast is not None
    result = OperatingForecastV1(
        status="prepared" if prepared else "abstained",
        model_id=model_id,
        model_version=model_version,
        policy_id=policy_id,
        policy_version=policy_version,
        mapping_version=mapping_version,
        profile_id=profile.profile_id,
        profile_digest=profile.digest,
        data_release_manifest_digest=data_release_manifest_digest,
        snapshot_id=snapshot.snapshot_id,
        quality_status=QualityStatus.PROVISIONAL if prepared else QualityStatus.ABSTAIN,
        issue_codes=tuple(dict.fromkeys((*selected.issue_codes, *metrics.issue_codes))),
        missing_evidence=tuple(sorted(set(metrics.missing_evidence))),
        selected_fact_ids=selected_fact_ids,
        rejected_fact_ids=selected.rejected_fact_ids,
        fiscal_years=fiscal_years,
        history_window_years=history_window_years,
        history_window_policy=HISTORY_WINDOW_POLICY
        if history_window_years is not None
        else None,
        excluded_history_fact_ids=excluded_history_fact_ids,
        historical_metrics=metrics,
        forecast=forecast,
        tax_rate=tax_rate,
        nodes=nodes,
        input_digest=input_digest,
        output_digest="0" * 64,
    )
    return result.model_copy(
        update={
            "output_digest": sha256_digest(result.model_dump(exclude={"output_digest"}))
        }
    )
