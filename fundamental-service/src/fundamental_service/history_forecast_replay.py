"""Execute release-bound history forecasts without accepting caller assumptions."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .annual_history import AnnualHistoryError, resolve_annual_history
from .contracts import (
    CalculationArtifactV1,
    InitialModelId,
    QualityStatus,
    SourceSnapshotV1,
    StrictModel,
    ValuationEvidenceReadRequestV1,
    ValuationEvidenceReadResponseV1,
    ValuationInputV1,
)
from .history_replay import ArtifactWriteResult, _safe_child, _write_content_addressed
from .history_mapping_audit import (
    ROOT,
    _filings,
    _load_snapshot_for,
    _read_json,
    _selected_issuers,
)
from .history_sufficiency_report import (
    MINIMUM_ISSUER_CLUSTERS,
    Filing,
    first_subsequent_original_filing,
)
from .operations import ServiceError
from .policies import PolicyRecordV1
from .serialization import sha256_digest
from .uncertainty import UncertaintyReportV1
from .valuation_preparation import (
    AutomaticValuationPreparationV1,
    derive_historical_metrics,
)
from .valuation_requirements import valuation_requirements_profile

FIXED_COHORT_DIGEST = "afad3f92f2597383d16afec2cc85850fbf5919106d3cb827a6e8112022836242"


class HistoryReplayService(Protocol):
    """Implemented by FundamentalApplication; no data publication is exposed."""

    def snapshot(self, snapshot_id: str) -> SourceSnapshotV1: ...

    def policy(self, policy_id: str) -> PolicyRecordV1: ...

    def read_valuation_evidence(
        self, request: ValuationEvidenceReadRequestV1
    ) -> ValuationEvidenceReadResponseV1: ...

    def prepare_valuation(
        self, request: ValuationEvidenceReadRequestV1
    ) -> AutomaticValuationPreparationV1: ...

    def calculate_valuation(
        self, value: ValuationInputV1, *, correlation_id: str
    ) -> CalculationArtifactV1 | UncertaintyReportV1: ...


class ReplayReleasePinV1(StrictModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_release_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_policy_version: str = Field(min_length=1)


class ReplayModelPinV1(StrictModel):
    model_id: InitialModelId
    model_version: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReplayOriginV1(StrictModel):
    decision: Filing
    filings: tuple[Filing, ...] = Field(min_length=1)
    forecast_release: ReplayReleasePinV1 | None = None
    label_release: ReplayReleasePinV1 | None = None

    @model_validator(mode="after")
    def inventory_is_coherent(self) -> ReplayOriginV1:
        if self.decision.form != "10-K" or self.filings.count(self.decision) != 1:
            raise ValueError("origin must identify one original annual filing")
        if len({filing.accession for filing in self.filings}) != len(self.filings):
            raise ValueError("filing inventory contains duplicate accessions")
        for filing in self.filings:
            if (
                filing.issuer_id != self.decision.issuer_id
                or filing.accepted_at.tzinfo is None
                or filing.accepted_at.utcoffset() is None
            ):
                raise ValueError("filing inventory issuer/timezone mismatch")
        return self


class HistoryEvidenceProtocolV1(StrictModel):
    protocol_version: Literal["history-length-evidence-v1"] = (
        "history-length-evidence-v1"
    )
    minimum_independent_issuers: Literal[100] = 100
    comparison: Literal["observed_complete_trailing_annual_periods"] = (
        "observed_complete_trailing_annual_periods"
    )
    promotion_policy_digest: None = None


class HistoryReplayPlanV1(StrictModel):
    protocol_version: Literal["release-bound-history-replay-v2"] = (
        "release-bound-history-replay-v2"
    )
    history_evidence_protocol: HistoryEvidenceProtocolV1 = HistoryEvidenceProtocolV1()
    cohort_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_version: str = Field(min_length=1)
    source_selection_policy: Literal["pit-v1"] = "pit-v1"
    evidence_class: Literal["calibration", "engineering"] = "calibration"
    runtime: dict[str, str]
    models: tuple[ReplayModelPinV1, ...] = Field(min_length=1)
    origins: tuple[ReplayOriginV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identities_are_unique(self) -> HistoryReplayPlanV1:
        keys = [(o.decision.issuer_id, o.decision.accession) for o in self.origins]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate replay origin")
        if len({model.model_id for model in self.models}) != len(self.models):
            raise ValueError("duplicate replay model")
        return self


def validate_fixed_cohort(
    plan: HistoryReplayPlanV1, *, cohort_root: Path = ROOT
) -> None:
    """Calibration cannot change issuers, dates, or the frozen filing inventory."""

    if plan.cohort_digest != FIXED_COHORT_DIGEST:
        raise ValueError("replay plan differs from the fixed SEC cohort digest")
    manifest_path = cohort_root / (
        "docs/acceptance/issue-359-sec-cohort-v1/capture_manifest.json"
    )
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != FIXED_COHORT_DIGEST:
        raise ValueError("replay evidence differs from the fixed SEC cohort digest")
    manifest = _read_json(manifest_path, "fixed cohort")
    for field in ("protocol", "frame_manifest"):
        path = _safe_child(cohort_root, manifest.get(f"{field}_path"), field)
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get(
            f"{field}_sha256"
        ):
            raise ValueError(f"replay cohort {field} hash mismatch")
    selected = _selected_issuers(manifest, root=cohort_root)
    by_key = {
        (origin.decision.issuer_id, origin.decision.accession): origin
        for origin in plan.origins
    }
    expected = {
        (str(row["issuer_id"]), str(row["decision_accession"])) for row in selected
    }
    if set(by_key) != expected or len(plan.origins) != len(selected):
        raise ValueError("replay plan replaced or omitted fixed cohort origins")
    if {model.model_id for model in plan.models} != {"fcff_dcf", "transition_fcff_dcf"}:
        raise ValueError("fixed cohort replay must retain both predeclared models")
    for row in selected:
        issuer_id, accession = str(row["issuer_id"]), str(row["decision_accession"])
        inventory = _filings(_load_snapshot_for(cohort_root, row), issuer_id)
        origin = by_key[(issuer_id, accession)]
        decision = next(filing for filing in inventory if filing.accession == accession)
        if origin.decision != decision or set(origin.filings) != set(inventory):
            raise ValueError("replay changed a fixed decision or filing inventory")


def _refusal(code: str) -> ServiceError:
    return ServiceError(code, code, status_code=422, retryable=False)


def _read_bound_evidence(
    service: HistoryReplayService,
    pin: ReplayReleasePinV1,
    filing: Filing,
    model_id: InitialModelId,
    mapping_version: str,
) -> tuple[SourceSnapshotV1, ValuationEvidenceReadResponseV1]:
    snapshot = service.snapshot(pin.snapshot_id)
    if (
        snapshot.snapshot_id != pin.snapshot_id
        or snapshot.manifest_digest != pin.snapshot_manifest_digest
        or snapshot.identity.issuer_id != filing.issuer_id
        or snapshot.valuation_timestamp != filing.accepted_at
        or snapshot.policy_version != pin.source_policy_version
    ):
        raise _refusal("REPLAY_SNAPSHOT_PIN_MISMATCH")
    if any(
        source.available_at > filing.accepted_at for source in snapshot.source_records
    ):
        raise _refusal("REPLAY_FUTURE_SOURCE_EVIDENCE")
    evidence = service.read_valuation_evidence(
        ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=pin.snapshot_id,
            data_release_manifest_digest=pin.data_release_manifest_digest,
            model_id=model_id,
        )
    )
    if (
        evidence.snapshot_id != pin.snapshot_id
        or evidence.snapshot_manifest_digest != pin.snapshot_manifest_digest
        or evidence.data_release_manifest_digest != pin.data_release_manifest_digest
        or evidence.identity.issuer_id != filing.issuer_id
        or evidence.valuation_timestamp != filing.accepted_at
        or evidence.model_id != model_id
        or any(fact.available_at > filing.accepted_at for fact in evidence.facts)
    ):
        raise _refusal("REPLAY_EVIDENCE_PIN_MISMATCH")
    if evidence.mapping_version != mapping_version:
        raise _refusal("REPLAY_MAPPING_PIN_MISMATCH")
    return snapshot, evidence


def _forecast(
    service: HistoryReplayService,
    plan: HistoryReplayPlanV1,
    origin: ReplayOriginV1,
    model: ReplayModelPinV1,
) -> dict[str, object]:
    issues: tuple[str, ...] = ()
    row: dict[str, object] = {
        "origin_digest": sha256_digest(asdict(origin.decision)),
        "issuer_id": origin.decision.issuer_id,
        "decision": asdict(origin.decision),
        "model": model,
        "status": "abstain",
        "issue_codes": (),
        "targets": {},
        "composer_invoked": False,
        "complete_history_years": None,
    }
    try:
        if origin.forecast_release is None:
            raise _refusal("REPLAY_FORECAST_RELEASE_UNAVAILABLE")
        pin = origin.forecast_release
        _, evidence = _read_bound_evidence(
            service, pin, origin.decision, model.model_id, plan.mapping_version
        )
        row["fact_evidence"] = evidence
        policy = service.policy(model.policy_id)
        if (
            policy.policy_digest != model.policy_digest
            or policy.policy_version != model.policy_version
            or policy.model_id != model.model_id
            or policy.model_version != model.model_version
            or policy.effective_at > origin.decision.accepted_at
            or policy.market_inputs is None
            or any(
                item.available_at > origin.decision.accepted_at
                for item in policy.market_inputs.evidence
            )
        ):
            raise _refusal("REPLAY_POLICY_PIN_MISMATCH")
        row["policy_evidence"] = policy
        row["composer_invoked"] = True
        preparation = service.prepare_valuation(
            ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=pin.snapshot_id,
                data_release_manifest_digest=pin.data_release_manifest_digest,
                model_id=model.model_id,
            )
        )
        row["preparation"] = preparation
        history_ends = {
            metric.period_end
            for metric in preparation.historical_metrics.metrics
            if metric.metric_id == "operating_margin"
        }
        if (
            preparation.historical_metrics.metrics
            or preparation.historical_metrics.quality_status
            is not QualityStatus.ABSTAIN
        ):
            row["complete_history_years"] = len(history_ends)
        issues = preparation.issue_codes
        row["issue_codes"] = preparation.issue_codes
        if preparation.input is None:
            row["preparation_status"] = preparation.status
            row["missing_evidence"] = preparation.missing_evidence
            return row
        value = preparation.input
        if (
            preparation.policy_id != model.policy_id
            or preparation.policy_version != model.policy_version
            or preparation.model_version != model.model_version
            or value.provenance.mapping_version != plan.mapping_version
            or value.valuation_context.source_selection_policy
            != plan.source_selection_policy
            or value.valuation_context.data_release_manifest_digest
            != pin.data_release_manifest_digest
        ):
            raise _refusal("REPLAY_PREPARATION_PIN_MISMATCH")
        if (
            not history_ends
            or max(history_ends) != origin.decision.period_end.isoformat()
        ):
            raise _refusal("REPLAY_FORECAST_ORIGIN_PERIOD_MISMATCH")
        result = service.calculate_valuation(
            value, correlation_id="issue-361-history-replay"
        )
        base = result.base if isinstance(result, UncertaintyReportV1) else result
        if (
            base.snapshot_id != pin.snapshot_id
            or base.valuation_timestamp != origin.decision.accepted_at
            or base.model_version != model.model_version
            or base.policy_resolution is None
            or base.policy_resolution.policy_digest != model.policy_digest
        ):
            raise _refusal("REPLAY_CALCULATION_PIN_MISMATCH")
        row["calculation"] = result
        quality = (
            result.status
            if isinstance(result, UncertaintyReportV1)
            else base.quality_status
        )
        row["status"] = quality.value
        if quality not in {QualityStatus.PROVISIONAL, QualityStatus.VERIFIED}:
            raise _refusal("REPLAY_FORECAST_UNCERTAINTY_NOT_USABLE")
        row["targets"] = {
            target: node.value
            for target, node_id in (("revenue", "revenue_1"), ("fcff", "fcff_1"))
            for node in base.nodes
            if node.node_id == node_id
        }
        if len(_targets(row)) != 2:
            row["targets"] = {}
            raise _refusal("REPLAY_FORECAST_TARGETS_UNAVAILABLE")
    except ServiceError as error:
        row["status"] = "abstain"
        row["issue_codes"] = tuple(sorted({*issues, error.code}))
        row["service_failure"] = {
            "code": error.code,
            "status_code": error.status_code,
            "retryable": error.retryable,
        }
    return row


def _label(
    service: HistoryReplayService,
    origin: ReplayOriginV1,
    model_id: InitialModelId,
    mapping_version: str,
) -> dict[str, object]:
    following = first_subsequent_original_filing(origin.decision, origin.filings)
    row: dict[str, object] = {
        "origin_digest": sha256_digest(asdict(origin.decision)),
        "issuer_id": origin.decision.issuer_id,
        "model_id": model_id,
        "first_subsequent_original": asdict(following) if following else None,
        "status": "incomplete",
        "targets": {},
    }
    try:
        if following is None:
            raise _refusal("REPLAY_FIRST_SUBSEQUENT_ORIGINAL_UNAVAILABLE")
        if not 300 <= (following.period_end - origin.decision.period_end).days <= 380:
            raise _refusal("REPLAY_LABEL_HORIZON_MISMATCH")
        if origin.label_release is None:
            raise _refusal("REPLAY_LABEL_RELEASE_UNAVAILABLE")
        snapshot, evidence = _read_bound_evidence(
            service, origin.label_release, following, model_id, mapping_version
        )
        row["fact_evidence"] = evidence
        facts = tuple(
            fact
            for fact in evidence.facts
            if fact.accession_number == following.accession
            and not fact.is_amendment
            and fact.quality is QualityStatus.VERIFIED
        )
        row["excluded_label_fact_ids"] = tuple(
            sorted(
                {fact.fact_id for fact in evidence.facts}
                - {fact.fact_id for fact in facts}
            )
        )
        revenues = tuple(
            fact
            for fact in facts
            if fact.normalized_field == "revenue"
            and fact.period_end == following.period_end
            and fact.period_start is not None
            and 300 <= (fact.period_end - fact.period_start).days <= 380
            and fact.unit == "USD"
            and fact.currency == "USD"
            and not fact.context.dimensions
            and fact.context.consolidation_scope == "consolidated"
            and isinstance(fact.value, Decimal)
        )
        targets: dict[str, Decimal] = {}
        if (
            revenues
            and len({(fact.period_start, fact.value) for fact in revenues}) == 1
        ):
            revenue = revenues[0].value
            assert isinstance(revenue, Decimal)
            targets["revenue"] = revenue
        history = resolve_annual_history(
            facts,
            snapshot=snapshot,
            valuation_timestamp=following.accepted_at,
            profile=valuation_requirements_profile(model_id),
        )
        metrics = derive_historical_metrics(history)
        row["historical_metrics"] = metrics
        for metric in metrics.metrics:
            if (
                metric.metric_id == "realized_fcff"
                and metric.period_end == following.period_end.isoformat()
            ):
                targets["fcff"] = metric.value
        row["targets"] = targets
        row["status"] = "complete" if len(targets) == 2 else "incomplete"
        row["missing_targets"] = tuple(sorted({"revenue", "fcff"} - targets.keys()))
        row["issue_codes"] = tuple(
            sorted(
                {
                    *metrics.issue_codes,
                    *(
                        ("REPLAY_LABEL_REVENUE_MISSING_OR_CONFLICTING",)
                        if "revenue" not in targets
                        else ()
                    ),
                }
            )
        )
    except (ServiceError, AnnualHistoryError) as error:
        row["issue_codes"] = (error.code,)
    return row


def _targets(row: dict[str, object]) -> dict[str, Decimal]:
    raw = row["targets"]
    if not isinstance(raw, dict):
        raise ValueError("replay targets must be an object")
    targets: dict[str, Decimal] = {}
    for name, value in raw.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, Decimal)
            or not value.is_finite()
        ):
            raise ValueError("replay targets must contain finite Decimal values")
        targets[name] = value
    return targets


def _accuracy_summary(
    forecasts: list[dict[str, object]], labels: list[dict[str, object]]
) -> dict[str, object]:
    targets: dict[str, object] = {}
    for target in ("revenue", "fcff"):
        errors: list[Decimal] = []
        issuer_errors: dict[str, list[Decimal]] = defaultdict(list)
        for forecast, label in zip(forecasts, labels, strict=True):
            predicted = _targets(forecast)
            realized = _targets(label)
            if target in predicted and target in realized:
                error = predicted[target] - realized[target]
                errors.append(error)
                issuer_errors[str(forecast["issuer_id"])].append(abs(error))
        count = len(errors)
        issuer_means = [
            sum(values, Decimal(0)) / len(values)
            for _, values in sorted(issuer_errors.items())
        ]
        cluster_count = len(issuer_means)
        standard_error = None
        if cluster_count >= 2:
            mean = sum(issuer_means, Decimal(0)) / cluster_count
            standard_error = (
                sum(((value - mean) ** 2 for value in issuer_means), Decimal(0))
                / (cluster_count - 1)
                / cluster_count
            ).sqrt()
        targets[target] = {
            "paired_origins": count,
            "independent_issuer_count": cluster_count,
            "mean_error": sum(errors, Decimal(0)) / count if count else None,
            "mean_absolute_error": sum((abs(value) for value in errors), Decimal(0))
            / count
            if count
            else None,
            "root_mean_squared_error": (
                sum((value**2 for value in errors), Decimal(0)) / count
            ).sqrt()
            if count
            else None,
            "issuer_mean_absolute_error_standard_error": standard_error,
            "uncertainty_method": "sample standard error of issuer-level mean absolute errors; undefined below two issuers",
        }
    return {
        "selected_origins": len(forecasts),
        "selected_independent_issuers": len({row["issuer_id"] for row in forecasts}),
        "forecast_coverage": sum(bool(row["targets"]) for row in forecasts),
        "complete_labels": sum(row["status"] == "complete" for row in labels),
        "dispositions": dict(
            sorted(Counter(str(row["status"]) for row in forecasts).items())
        ),
        "forecast_issue_counts": _issue_counts(forecasts),
        "label_issue_counts": _issue_counts(labels),
        "targets": targets,
    }


def _summary(
    forecasts: list[dict[str, object]],
    labels: list[dict[str, object]],
    *,
    model_id: InitialModelId,
    evidence_class: Literal["calibration", "engineering"],
) -> dict[str, object]:
    summary = _accuracy_summary(forecasts, labels)
    pairs = [
        (forecast, label)
        for forecast, label in zip(forecasts, labels, strict=True)
        if label["status"] == "complete"
        and set(_targets(forecast)) == set(_targets(label)) == {"revenue", "fcff"}
    ]
    issuers = {str(forecast["issuer_id"]) for forecast, _ in pairs}
    empirical_status = (
        "not_measured"
        if not pairs
        else "empirical_underpowered"
        if len(issuers) < MINIMUM_ISSUER_CLUSTERS
        else "measured_review_required"
    )
    execution_status = (
        "blocked"
        if not summary["forecast_coverage"]
        else "complete"
        if len(pairs) == len(forecasts)
        else "partial"
    )
    strata = []
    window = valuation_requirements_profile(model_id).history_window_years
    if any(
        years is not None
        and (
            not isinstance(years, int)
            or isinstance(years, bool)
            or not 0 <= years <= window
        )
        for forecast in forecasts
        for years in (forecast["complete_history_years"],)
    ):
        raise ValueError("history length differs from the service requirements window")
    for years in (*range(window + 1), None):
        selected = [
            (forecast, label)
            for forecast, label in zip(forecasts, labels, strict=True)
            if forecast["complete_history_years"] == years
        ]
        strata.append(
            {
                "complete_history_years": years,
                "missing_reason": "composer_history_unavailable"
                if years is None
                else None,
                **_accuracy_summary(
                    [forecast for forecast, _ in selected],
                    [label for _, label in selected],
                ),
            }
        )
    return {
        **summary,
        "paired_complete_origins": len(pairs),
        "paired_complete_independent_issuers": len(issuers),
        "execution_status": execution_status,
        "empirical_status": empirical_status,
        "history_length_comparison": {
            "protocol_version": "history-length-evidence-v1",
            "cohort_origins": len(forecasts),
            "minimum_independent_issuers": MINIMUM_ISSUER_CLUSTERS,
            "minimum_is_sufficient_for_promotion": False,
            "method": "descriptive groups by observed complete trailing annual periods; no truncated-history refits or causal comparisons",
            "strata": strata,
        },
        "supported_history_threshold": None,
        "threshold_decision": "engineering_only"
        if evidence_class == "engineering"
        else "engineering_blocked"
        if execution_status == "blocked"
        else "unmeasured_no_complete_pairs"
        if not pairs
        else empirical_status,
        "promotion_missing_evidence": (
            "reviewed_accuracy_and_power_criteria",
            "reviewed_history_length_comparison_and_promotion_policy",
        ),
    }


def _issue_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        codes = row.get("issue_codes", ())
        if not isinstance(codes, (tuple, list)) or not all(
            isinstance(code, str) for code in codes
        ):
            raise ValueError("replay issue codes must be text")
        counts.update(str(code) for code in codes)
    return dict(sorted(counts.items()))


def run_history_replay(
    service: HistoryReplayService,
    plan: HistoryReplayPlanV1,
    *,
    cohort_root: Path = ROOT,
) -> dict[str, dict[str, object]]:
    """Finish all chronological forecasts before reading any subsequent labels."""

    if plan.evidence_class == "calibration":
        validate_fixed_cohort(plan, cohort_root=cohort_root)
    origins = sorted(
        plan.origins,
        key=lambda o: (
            o.decision.accepted_at,
            o.decision.issuer_id,
            o.decision.accession,
        ),
    )
    origins = [
        origin.model_copy(
            update={
                "filings": tuple(
                    sorted(
                        origin.filings,
                        key=lambda filing: (filing.accepted_at, filing.accession),
                    )
                )
            }
        )
        for origin in origins
    ]
    models = sorted(plan.models, key=lambda model: model.model_id)
    normalized = plan.model_copy(
        update={"origins": tuple(origins), "models": tuple(models)}
    )
    with localcontext(Context(prec=50)):
        forecasts = [
            _forecast(service, normalized, origin, model)
            for origin in origins
            for model in models
        ]
        labels = [
            _label(service, origin, model.model_id, plan.mapping_version)
            for origin in origins
            for model in models
        ]
        summaries = {
            model.model_id: _summary(
                forecasts[index :: len(models)],
                labels[index :: len(models)],
                model_id=model.model_id,
                evidence_class=plan.evidence_class,
            )
            for index, model in enumerate(models)
        }
    inputs = normalized.model_dump(mode="python")
    forecast_output: dict[str, object] = {
        "input_digest": sha256_digest(inputs),
        "rows": forecasts,
    }
    label_output: dict[str, object] = {
        "input_digest": sha256_digest(inputs),
        "rows": labels,
    }
    scores = []
    for forecast, label in zip(forecasts, labels, strict=True):
        predicted, realized = _targets(forecast), _targets(label)
        for target in ("revenue", "fcff"):
            expected, observed = predicted.get(target), realized.get(target)
            with localcontext(Context(prec=50)):
                residual = (
                    expected - observed
                    if expected is not None and observed is not None
                    else None
                )
                scores.append(
                    {
                        "origin_digest": forecast["origin_digest"],
                        "issuer_id": forecast["issuer_id"],
                        "model_id": label["model_id"],
                        "target": target,
                        "forecast": expected,
                        "label": observed,
                        "error": residual,
                        "absolute_error": abs(residual)
                        if residual is not None
                        else None,
                        "absolute_percentage_error": abs(residual / observed)
                        if residual is not None and observed
                        else None,
                        "percentage_error_missing_reason": "zero_label_denominator"
                        if observed == 0
                        else "unpaired_forecast_or_label"
                        if residual is None
                        else None,
                        "forecast_issue_codes": forecast["issue_codes"],
                        "label_issue_codes": label["issue_codes"],
                    }
                )
    score_output: dict[str, object] = {
        "forecast_digest": sha256_digest(forecast_output),
        "label_digest": sha256_digest(label_output),
        "rows": scores,
    }
    report: dict[str, object] = {
        "protocol_version": plan.protocol_version,
        "history_evidence_protocol": plan.history_evidence_protocol.model_dump(),
        "evidence_class": plan.evidence_class,
        "runtime": plan.runtime,
        "input_digest": sha256_digest(inputs),
        "forecast_digest": sha256_digest(forecast_output),
        "label_digest": sha256_digest(label_output),
        "score_digest": sha256_digest(score_output),
        "models": summaries,
        "composer_invocations": sum(
            row["composer_invoked"] is True for row in forecasts
        ),
        "supported_history_threshold": None,
        "status": "engineering_only"
        if plan.evidence_class == "engineering"
        else "engineering_blocked"
        if all(row["forecast_coverage"] == 0 for row in summaries.values())
        else "unmeasured_no_complete_pairs"
        if all(row["paired_complete_origins"] == 0 for row in summaries.values())
        else "empirical_evidence_requires_review",
    }
    return {
        "input": inputs,
        "forecast": forecast_output,
        "label": label_output,
        "score": score_output,
        "report": report,
    }


def write_history_replay(
    artifacts: dict[str, dict[str, object]], output_directory: Path
) -> dict[str, ArtifactWriteResult]:
    return {
        kind: _write_content_addressed(output_directory, kind, value)
        for kind, value in sorted(artifacts.items())
    }
