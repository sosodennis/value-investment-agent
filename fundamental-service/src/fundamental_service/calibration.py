"""Point-in-time calibration evidence and release quality gates.

Calibration evaluates forecast or interval targets. It never changes the
deterministic valuation result and never uses a later market price as intrinsic
value ground truth.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .serialization import sha256_digest


class CalibrationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ForecastObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    forecast_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    decision_timestamp: datetime
    target_period_start: datetime
    target_period_end: datetime
    forecast_value: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    source_snapshot_id: str = Field(min_length=1)
    provider_fallback: bool = False
    evidence_class: Literal["calibration", "engineering"] = "calibration"
    industry_cohort: str = "unassigned"
    interval_confidence: float = Field(default=0.8, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_window(self) -> "ForecastObservationV1":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (
                self.decision_timestamp,
                self.target_period_start,
                self.target_period_end,
            )
        ):
            raise ValueError("decision_timestamp must include timezone")
        if self.target_period_start > self.target_period_end:
            raise ValueError("target period is reversed")
        if self.lower_bound is not None and self.upper_bound is not None:
            if self.lower_bound > self.upper_bound:
                raise ValueError("interval bounds are reversed")
            if not self.lower_bound <= self.forecast_value <= self.upper_bound:
                raise ValueError("forecast must lie inside its interval")
        if not all(
            math.isfinite(value)
            for value in (self.forecast_value, self.lower_bound, self.upper_bound)
            if value is not None
        ):
            raise ValueError("forecast values must be finite")
        return self


class PublishedOutcomeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    period_end: datetime
    published_at: datetime
    value: float
    source_snapshot_id: str = Field(min_length=1)
    is_restatement: bool = False

    @model_validator(mode="after")
    def validate_value(self) -> "PublishedOutcomeV1":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.period_end, self.published_at)
        ):
            raise ValueError("outcome timestamps must include timezone")
        if not math.isfinite(self.value):
            raise ValueError("outcome value must be finite")
        return self


class CalibrationLabelV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    forecast_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    decision_timestamp: datetime
    target_period_end: datetime
    target_period_start: datetime | None = None
    forecast_value: float
    realized_value: float
    label_available_at: datetime
    source_snapshot_id: str = Field(min_length=1)
    forecast_source_snapshot_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    restatement_outcome_ids: tuple[str, ...] = ()
    lower_bound: float | None = None
    upper_bound: float | None = None
    provider_fallback: bool = False
    industry_cohort: str = "unassigned"
    interval_confidence: float = Field(default=0.8, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_timestamps_and_values(self) -> "CalibrationLabelV1":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (
                self.decision_timestamp,
                self.target_period_start,
                self.target_period_end,
                self.label_available_at,
            )
        ):
            raise ValueError("calibration label timestamps must include timezone")
        if not all(
            math.isfinite(value)
            for value in (
                self.forecast_value,
                self.realized_value,
                self.lower_bound,
                self.upper_bound,
            )
            if value is not None
        ):
            raise ValueError("calibration label values must be finite")
        if (
            self.target_period_start is not None
            and self.target_period_start > self.target_period_end
        ):
            raise ValueError("calibration target period is reversed")
        if self.label_available_at <= self.decision_timestamp:
            raise ValueError("label must be published after the forecast decision")
        if self.lower_bound is not None and self.upper_bound is not None:
            if self.lower_bound > self.upper_bound:
                raise ValueError("calibration interval bounds are reversed")
            if not self.lower_bound <= self.forecast_value <= self.upper_bound:
                raise ValueError("forecast must lie inside its calibration interval")
        return self


class ExcludedCalibrationRowV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    forecast_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    reason: Literal[
        "no_eligible_label",
        "label_after_cutoff",
        "overlap_purged",
        "embargoed",
        "issuer_leakage",
        "missing_value",
        "duplicate_forecast",
        "engineering_cohort",
    ]
    detail: str = Field(min_length=1)


class LabelBuildReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    labels: tuple[CalibrationLabelV1, ...] = ()
    excluded: tuple[ExcludedCalibrationRowV1, ...] = ()
    restatement_diagnostics: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    label_rule_version: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_matches(self) -> "LabelBuildReportV1":
        label_ids = [label.forecast_id for label in self.labels]
        if len(set(label_ids)) != len(label_ids):
            raise ValueError("label build report forecast IDs must be unique")
        if self.manifest_digest != sha256_digest(
            self.model_dump(exclude={"manifest_digest"})
        ):
            raise ValueError("label manifest digest mismatch")
        return self


def build_point_in_time_labels(
    forecasts: tuple[ForecastObservationV1, ...],
    outcomes: tuple[PublishedOutcomeV1, ...],
    *,
    cutoff: datetime | None = None,
    label_rule_version: str = "pit-first-publication-v1",
) -> LabelBuildReportV1:
    """Bind each forecast to the first eligible later publication.

    Restatements remain diagnostics and never replace the first label used for
    the original point-in-time score.
    """
    if cutoff is not None and (cutoff.tzinfo is None or cutoff.utcoffset() is None):
        raise CalibrationError(
            "TIMEZONE_REQUIRED", "label cutoff must include timezone"
        )
    labels: list[CalibrationLabelV1] = []
    excluded: list[ExcludedCalibrationRowV1] = []
    diagnostics: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for forecast in sorted(forecasts, key=lambda row: row.forecast_id):
        if forecast.forecast_id in seen:
            excluded.append(
                ExcludedCalibrationRowV1(
                    forecast_id=forecast.forecast_id,
                    issuer_id=forecast.issuer_id,
                    reason="duplicate_forecast",
                    detail="forecast ID is not unique",
                )
            )
            continue
        seen.add(forecast.forecast_id)
        if forecast.evidence_class == "engineering":
            excluded.append(
                ExcludedCalibrationRowV1(
                    forecast_id=forecast.forecast_id,
                    issuer_id=forecast.issuer_id,
                    reason="engineering_cohort",
                    detail="engineering/golden fixtures are excluded from calibration evidence",
                )
            )
            continue
        candidates = sorted(
            (
                outcome
                for outcome in outcomes
                if outcome.issuer_id == forecast.issuer_id
                and outcome.target == forecast.target
                and outcome.period_end == forecast.target_period_end
                and outcome.published_at > forecast.decision_timestamp
                and (cutoff is None or outcome.published_at <= cutoff)
            ),
            key=lambda outcome: (outcome.published_at, outcome.outcome_id),
        )
        primary = next(
            (outcome for outcome in candidates if not outcome.is_restatement), None
        )
        if primary is None:
            excluded.append(
                ExcludedCalibrationRowV1(
                    forecast_id=forecast.forecast_id,
                    issuer_id=forecast.issuer_id,
                    reason="no_eligible_label",
                    detail="no first subsequently published eligible outcome",
                )
            )
            continue
        restatements = tuple(
            outcome.outcome_id
            for outcome in candidates
            if outcome.outcome_id != primary.outcome_id
            and (outcome.is_restatement or outcome.published_at > primary.published_at)
        )
        if restatements:
            diagnostics[forecast.forecast_id] = restatements
        labels.append(
            CalibrationLabelV1(
                forecast_id=forecast.forecast_id,
                issuer_id=forecast.issuer_id,
                target=forecast.target,
                decision_timestamp=forecast.decision_timestamp,
                target_period_end=forecast.target_period_end,
                target_period_start=forecast.target_period_start,
                forecast_value=forecast.forecast_value,
                realized_value=primary.value,
                label_available_at=primary.published_at,
                source_snapshot_id=primary.source_snapshot_id,
                forecast_source_snapshot_id=forecast.source_snapshot_id,
                outcome_id=primary.outcome_id,
                restatement_outcome_ids=restatements,
                lower_bound=forecast.lower_bound,
                upper_bound=forecast.upper_bound,
                provider_fallback=forecast.provider_fallback,
                industry_cohort=forecast.industry_cohort,
                interval_confidence=forecast.interval_confidence,
            )
        )
    payload = {
        "labels": tuple(labels),
        "excluded": tuple(excluded),
        "restatement_diagnostics": diagnostics,
        "label_rule_version": label_rule_version,
    }
    return LabelBuildReportV1(**payload, manifest_digest=sha256_digest(payload))


class SplitPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    split_policy_version: str = Field(min_length=1)
    train_end: datetime
    validation_end: datetime
    oos_end: datetime
    purge_days: int = Field(ge=0)
    embargo_days: int = Field(ge=0)
    group_by_issuer: bool = True

    @model_validator(mode="after")
    def ordered_boundaries(self) -> "SplitPolicyV1":
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.train_end, self.validation_end, self.oos_end)
        ):
            raise ValueError("split boundaries must include timezone")
        if not self.train_end < self.validation_end < self.oos_end:
            raise ValueError("split boundaries must be chronological")
        return self


class SplitRowV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    forecast_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    split: Literal["train", "validation", "oos"]


class SplitManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: SplitPolicyV1
    included: tuple[SplitRowV1, ...] = ()
    excluded: tuple[ExcludedCalibrationRowV1, ...] = ()
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_matches(self) -> "SplitManifestV1":
        if self.manifest_digest != sha256_digest(
            self.model_dump(exclude={"manifest_digest"})
        ):
            raise ValueError("split manifest digest mismatch")
        return self


def build_split_manifest(
    labels: tuple[CalibrationLabelV1, ...], policy: SplitPolicyV1
) -> SplitManifestV1:
    included: list[SplitRowV1] = []
    excluded: list[ExcludedCalibrationRowV1] = []
    issuer_split: dict[str, str] = {}
    boundaries = (
        ("train", policy.train_end),
        ("validation", policy.validation_end),
        ("oos", policy.oos_end),
    )
    for label in sorted(
        labels, key=lambda row: (row.decision_timestamp, row.forecast_id)
    ):
        if label.label_available_at > policy.oos_end:
            excluded.append(
                ExcludedCalibrationRowV1(
                    forecast_id=label.forecast_id,
                    issuer_id=label.issuer_id,
                    reason="label_after_cutoff",
                    detail="label is unavailable by the declared OOS cutoff",
                )
            )
            continue
        split = next(
            (
                name
                for name, boundary in boundaries
                if label.decision_timestamp < boundary
            ),
            None,
        )
        if split is None:
            excluded.append(
                ExcludedCalibrationRowV1(
                    forecast_id=label.forecast_id,
                    issuer_id=label.issuer_id,
                    reason="label_after_cutoff",
                    detail="forecast is outside the declared split windows",
                )
            )
            continue
        # Purge and embargo apply on both sides of the train/validation
        # boundaries. The OOS horizon is bounded by label availability, so
        # there is no artificial purge at the end of that declared window.
        purge_delta = timedelta(days=policy.purge_days)
        embargo_delta = timedelta(days=policy.embargo_days)
        overlaps_boundary = any(
            label.target_period_end >= boundary - purge_delta
            and label.decision_timestamp <= boundary + embargo_delta
            for boundary in (policy.train_end, policy.validation_end)
        )
        if overlaps_boundary:
            excluded.append(
                ExcludedCalibrationRowV1(
                    forecast_id=label.forecast_id,
                    issuer_id=label.issuer_id,
                    reason="overlap_purged" if policy.purge_days else "embargoed",
                    detail="forecast window overlaps a split boundary",
                )
            )
            continue
        if policy.group_by_issuer:
            prior = issuer_split.get(label.issuer_id)
            if prior is not None and prior != split:
                excluded.append(
                    ExcludedCalibrationRowV1(
                        forecast_id=label.forecast_id,
                        issuer_id=label.issuer_id,
                        reason="issuer_leakage",
                        detail=f"issuer already assigned to {prior}",
                    )
                )
                continue
            issuer_split[label.issuer_id] = split
        included.append(
            SplitRowV1(
                forecast_id=label.forecast_id, issuer_id=label.issuer_id, split=split
            )
        )
    payload = {"policy": policy, "included": included, "excluded": excluded}
    return SplitManifestV1(
        policy=policy,
        included=tuple(included),
        excluded=tuple(excluded),
        manifest_digest=sha256_digest(payload),
    )


class ConfidenceIntervalV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confidence: float = Field(gt=0, lt=1)
    lower: float
    upper: float
    method: Literal["percentile-bootstrap", "wilson"]
    seed: int
    resamples: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ConfidenceIntervalV1":
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ValueError("confidence interval bounds must be finite")
        if self.lower > self.upper:
            raise ValueError("confidence interval bounds are reversed")
        return self


class ContinuousMetricsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_count: int = Field(ge=0)
    mae: float | None = None
    rmse: float | None = None
    median_absolute_error: float | None = None
    signed_bias: float | None = None
    scaled_error: float | None = None
    confidence_interval: ConfidenceIntervalV1 | None = None


class IntervalMetricsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_count: int = Field(ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1)
    mean_width: float | None = None
    interval_score: float | None = None
    coverage_confidence_interval: ConfidenceIntervalV1 | None = None


class MetricBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    continuous: ContinuousMetricsV1
    interval: IntervalMetricsV1 | None = None


def _bootstrap_interval(
    values: list[float], *, seed: int, resamples: int = 1000
) -> ConfidenceIntervalV1 | None:
    if not values:
        return None
    rng = random.Random(seed)
    samples = [
        sum(rng.choice(values) for _ in values) / len(values) for _ in range(resamples)
    ]
    samples.sort()
    return ConfidenceIntervalV1(
        confidence=0.95,
        lower=samples[int(resamples * 0.025)],
        upper=samples[int(resamples * 0.975) - 1],
        method="percentile-bootstrap",
        seed=seed,
        resamples=resamples,
    )


def _wilson_interval(
    successes: int, total: int, *, confidence: float = 0.95
) -> ConfidenceIntervalV1 | None:
    if total <= 0:
        return None
    # 1.959963984540054 is the fixed two-sided 95% normal quantile. Keeping
    # this constant avoids a scipy dependency in the deterministic service.
    z = 1.959963984540054 if confidence == 0.95 else 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return ConfidenceIntervalV1(
        confidence=confidence,
        lower=max(0.0, center - radius),
        upper=min(1.0, center + radius),
        method="wilson",
        seed=0,
        resamples=total,
    )


def _bootstrap_relative_improvement_interval(
    raw_errors: list[float],
    calibrated_errors: list[float],
    *,
    seed: int,
    resamples: int,
) -> ConfidenceIntervalV1 | None:
    if not raw_errors or len(raw_errors) != len(calibrated_errors):
        return None
    rng = random.Random(seed)
    improvements: list[float] = []
    for _ in range(resamples):
        indices = [rng.randrange(len(raw_errors)) for _ in raw_errors]
        raw_mae = sum(abs(raw_errors[index]) for index in indices) / len(indices)
        calibrated_mae = sum(abs(calibrated_errors[index]) for index in indices) / len(
            indices
        )
        improvements.append((raw_mae - calibrated_mae) / raw_mae if raw_mae else 0.0)
    improvements.sort()
    return ConfidenceIntervalV1(
        confidence=0.95,
        lower=improvements[int(resamples * 0.025)],
        upper=improvements[int(resamples * 0.975) - 1],
        method="percentile-bootstrap",
        seed=seed,
        resamples=resamples,
    )


def calculate_metric_bundle(
    labels: tuple[CalibrationLabelV1, ...],
    predictions: dict[str, float],
    naive_predictions: dict[str, float] | None = None,
    *,
    seed: int = 0,
    resamples: int = 1000,
) -> MetricBundleV1:
    if resamples < 1:
        raise CalibrationError("INVALID_RESAMPLES", "resamples must be positive")
    for value in (*predictions.values(), *(naive_predictions or {}).values()):
        if not math.isfinite(value):
            raise CalibrationError(
                "NON_FINITE_PREDICTION", "predictions must be finite"
            )
    rows = [label for label in labels if label.forecast_id in predictions]
    if not rows:
        return MetricBundleV1(
            continuous=ContinuousMetricsV1(sample_count=0), interval=None
        )
    errors = [predictions[row.forecast_id] - row.realized_value for row in rows]
    naive_rows = [
        row
        for row in rows
        if naive_predictions is not None and row.forecast_id in naive_predictions
    ]
    naive_errors = [
        naive_predictions[row.forecast_id] - row.realized_value for row in naive_rows
    ]
    absolute = [abs(error) for error in errors]
    naive_mae = (
        sum(abs(error) for error in naive_errors) / len(naive_errors)
        if naive_errors
        else 0.0
    )
    metrics = ContinuousMetricsV1(
        sample_count=len(rows),
        mae=sum(absolute) / len(rows),
        rmse=math.sqrt(sum(error * error for error in errors) / len(rows)),
        median_absolute_error=median(absolute),
        signed_bias=sum(errors) / len(rows),
        scaled_error=(sum(absolute) / len(rows)) / naive_mae if naive_mae else None,
        confidence_interval=_bootstrap_interval(errors, seed=seed, resamples=resamples),
    )
    interval_rows = [
        row
        for row in rows
        if row.lower_bound is not None and row.upper_bound is not None
    ]
    interval = None
    if interval_rows:
        covered = [
            row.lower_bound <= row.realized_value <= row.upper_bound
            for row in interval_rows
        ]
        scores = [
            (row.upper_bound - row.lower_bound)
            + (2 / (1 - row.interval_confidence))
            * (row.lower_bound - row.realized_value)
            * (row.realized_value < row.lower_bound)
            + (2 / (1 - row.interval_confidence))
            * (row.realized_value - row.upper_bound)
            * (row.realized_value > row.upper_bound)
            for row in interval_rows
        ]
        coverage = sum(covered) / len(covered)
        interval = IntervalMetricsV1(
            sample_count=len(interval_rows),
            coverage=coverage,
            mean_width=sum(row.upper_bound - row.lower_bound for row in interval_rows)
            / len(interval_rows),
            interval_score=sum(scores) / len(scores),
            coverage_confidence_interval=_wilson_interval(sum(covered), len(covered)),
        )
    return MetricBundleV1(continuous=metrics, interval=interval)


class PromotionPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1)
    minimum_oos_samples: int = Field(default=30, gt=0)
    minimum_cohort_samples: int = Field(default=10, gt=0)
    minimum_relative_improvement: float = Field(default=0.10, ge=0, le=1)
    minimum_improvement_confidence_lower: float = Field(default=0.0, ge=0, le=1)
    expected_interval_confidence: float = Field(default=0.8, gt=0, lt=1)
    minimum_interval_coverage: float | None = Field(default=0.8, ge=0, le=1)
    minimum_interval_coverage_confidence_lower: float = Field(default=0.70, ge=0, le=1)
    maximum_absolute_bias: float | None = Field(default=None, ge=0)
    require_oos_improvement_over_raw: bool = True
    require_oos_improvement_over_naive: bool = True
    maximum_provider_fallback_rate: float = Field(default=0, ge=0, le=1)
    maximum_missing_rate: float = Field(default=0, ge=0, le=1)
    maximum_abstention_rate: float = Field(default=0, ge=0, le=1)
    maximum_drift: float | None = Field(default=None, ge=0)
    expiry_days: int = Field(gt=0)


class CalibrationArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_id: str = Field(min_length=1)
    calibration_version: str = Field(min_length=1)
    status: Literal["active", "inactive", "rejected", "expired"]
    target: str = Field(min_length=1)
    target_layer: Literal["extraction", "forecast", "uncertainty", "model_selection"]
    metric: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    cohort_id: str = Field(min_length=1)
    training_window: tuple[datetime, datetime]
    data_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    feature_contract: str = Field(min_length=1)
    label_contract: str = Field(min_length=1)
    split_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_policy_version: str = Field(min_length=1)
    purge_days: int = Field(ge=0)
    embargo_days: int = Field(ge=0)
    model_class: str = Field(min_length=1)
    hyperparameters: dict[str, str] = Field(default_factory=dict)
    raw_metrics: MetricBundleV1
    calibrated_metrics: MetricBundleV1
    naive_metrics: MetricBundleV1
    sample_counts: dict[str, int]
    cohort_sample_counts: dict[str, int]
    cohort_metrics: dict[str, dict[str, MetricBundleV1]]
    missingness_counts: dict[str, int]
    abstention_count: int = Field(ge=0)
    label_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exclusion_manifest: tuple[ExcludedCalibrationRowV1, ...] = ()
    provider_fallback_rate: float = Field(ge=0, le=1)
    improvement_confidence_interval: ConfidenceIntervalV1 | None = None
    naive_improvement_confidence_interval: ConfidenceIntervalV1 | None = None
    confidence_method: str = Field(min_length=1)
    fallback_policy: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    review_status: Literal["pending", "approved", "rejected"]
    created_at: datetime
    expires_at: datetime
    policy_version: str = Field(min_length=1)
    quality_issue_codes: tuple[str, ...] = ()
    gate_reasons: tuple[str, ...] = ()
    affects_base_value: Literal[False] = False
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_matches(self) -> "CalibrationArtifactV1":
        if self.artifact_digest != sha256_digest(
            self.model_dump(exclude={"artifact_digest"})
        ):
            raise ValueError("calibration artifact digest mismatch")
        if self.expires_at <= self.created_at:
            raise ValueError("calibration expiry must be after creation")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (*self.training_window, self.created_at, self.expires_at)
        ):
            raise ValueError("calibration artifact timestamps must include timezone")
        if self.training_window[0] >= self.training_window[1]:
            raise ValueError("training window must be chronological")
        return self


def evaluate_calibration(
    labels: tuple[CalibrationLabelV1, ...],
    split_manifest: SplitManifestV1,
    *,
    label_build_report: LabelBuildReportV1,
    calibrated_predictions: dict[str, float],
    naive_predictions: dict[str, float],
    policy: PromotionPolicyV1,
    calibration_id: str,
    calibration_version: str,
    target_layer: Literal[
        "extraction", "forecast", "uncertainty", "model_selection", "market_outcome"
    ],
    target: str | None = None,
    metric: str,
    model_id: str,
    cohort_id: str,
    data_snapshot_ids: tuple[str, ...],
    feature_contract: str,
    label_contract: str,
    model_class: str,
    owner: str,
    now: datetime,
    training_window: tuple[datetime, datetime],
    hyperparameters: dict[str, str] | None = None,
    quality_issue_codes: tuple[str, ...] = (),
    drift: float | None = None,
    seed: int = 0,
    resamples: int = 1000,
) -> CalibrationArtifactV1:
    if target_layer == "market_outcome":
        raise CalibrationError(
            "MARKET_OUTCOME_SEPARATE_CONTRACT",
            "market outcomes require the separate signal-evaluation contract",
        )
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (now, *training_window)
    ):
        raise CalibrationError(
            "TIMEZONE_REQUIRED", "calibration timestamps must include timezone"
        )
    by_id = {label.forecast_id: label for label in labels}
    if len(by_id) != len(labels):
        raise CalibrationError(
            "DUPLICATE_LABEL", "calibration labels must have unique IDs"
        )
    report_labels = {
        label.forecast_id: sha256_digest(label.model_dump())
        for label in label_build_report.labels
    }
    evaluated_labels = {
        label.forecast_id: sha256_digest(label.model_dump()) for label in labels
    }
    if report_labels != evaluated_labels:
        raise CalibrationError(
            "LABEL_REPORT_MISMATCH",
            "label build report does not match the complete labels being evaluated",
        )
    targets = {label.target for label in labels}
    if target is not None and any(label.target != target for label in labels):
        raise CalibrationError("TARGET_MISMATCH", "labels contain a different target")
    if len(targets) > 1:
        raise CalibrationError(
            "MULTIPLE_TARGETS", "one calibration artifact must have one target"
        )
    resolved_target = target or (next(iter(targets)) if targets else "unknown")
    manifest_ids = [row.forecast_id for row in split_manifest.included]
    excluded_ids = [row.forecast_id for row in split_manifest.excluded]
    if (
        len(set(manifest_ids)) != len(manifest_ids)
        or len(set(excluded_ids)) != len(excluded_ids)
        or set(manifest_ids) & set(excluded_ids)
        or set(manifest_ids) | set(excluded_ids) != set(by_id)
    ):
        raise CalibrationError(
            "SPLIT_LABEL_MISMATCH",
            "split manifest must cover each evaluated label exactly once",
        )
    split_rows = tuple(split_manifest.included) + tuple(split_manifest.excluded)
    for row in split_rows:
        if row.issuer_id != by_id[row.forecast_id].issuer_id:
            raise CalibrationError(
                "SPLIT_LABEL_MISMATCH",
                "split manifest issuer does not match the evaluated label",
            )
    split_ids = {
        split: tuple(
            by_id[row.forecast_id]
            for row in split_manifest.included
            if row.split == split
        )
        for split in ("train", "validation", "oos")
    }
    reasons: list[str] = []
    oos_rows = split_ids["oos"]
    if not oos_rows:
        reasons.append("NO_OOS_EVIDENCE")
    comparable_oos_rows = tuple(
        label
        for label in oos_rows
        if label.forecast_id in calibrated_predictions
        and label.forecast_id in naive_predictions
    )
    raw_predictions = {label.forecast_id: label.forecast_value for label in labels}
    raw = calculate_metric_bundle(
        comparable_oos_rows,
        raw_predictions,
        naive_predictions,
        seed=seed,
        resamples=resamples,
    )
    calibrated = calculate_metric_bundle(
        comparable_oos_rows,
        calibrated_predictions,
        naive_predictions,
        seed=seed + 1,
        resamples=resamples,
    )
    naive = calculate_metric_bundle(
        comparable_oos_rows,
        naive_predictions,
        naive_predictions,
        seed=seed + 2,
        resamples=resamples,
    )
    if calibrated.continuous.sample_count < policy.minimum_oos_samples:
        reasons.append("INSUFFICIENT_OOS_SAMPLE")
    eligible_oos_rows = comparable_oos_rows
    cohort_counts: dict[str, int] = {}
    for label in eligible_oos_rows:
        cohort_counts[label.industry_cohort] = (
            cohort_counts.get(label.industry_cohort, 0) + 1
        )
    if cohort_counts and any(
        count < policy.minimum_cohort_samples for count in cohort_counts.values()
    ):
        reasons.append("INSUFFICIENT_COHORT_SAMPLE")
    cohort_metrics: dict[str, dict[str, MetricBundleV1]] = {}
    for index, cohort in enumerate(sorted(cohort_counts)):
        cohort_rows = tuple(
            label for label in comparable_oos_rows if label.industry_cohort == cohort
        )
        cohort_metrics[cohort] = {
            "raw": calculate_metric_bundle(
                cohort_rows,
                raw_predictions,
                naive_predictions,
                seed=seed + 10 + index * 3,
                resamples=resamples,
            ),
            "calibrated": calculate_metric_bundle(
                cohort_rows,
                calibrated_predictions,
                naive_predictions,
                seed=seed + 11 + index * 3,
                resamples=resamples,
            ),
            "naive": calculate_metric_bundle(
                cohort_rows,
                naive_predictions,
                naive_predictions,
                seed=seed + 12 + index * 3,
                resamples=resamples,
            ),
        }
    if policy.minimum_interval_coverage is not None:
        for cohort, metrics in cohort_metrics.items():
            interval = metrics["calibrated"].interval
            if (
                interval is None
                or interval.coverage is None
                or interval.coverage < policy.minimum_interval_coverage
            ):
                reasons.append("COHORT_COVERAGE_GATE_FAILED")
            if (
                interval is None
                or interval.coverage_confidence_interval is None
                or interval.coverage_confidence_interval.lower
                < policy.minimum_interval_coverage_confidence_lower
            ):
                reasons.append("COHORT_COVERAGE_CONFIDENCE_GATE_FAILED")
    raw_errors = [
        raw_predictions[label.forecast_id] - label.realized_value
        for label in comparable_oos_rows
    ]
    calibrated_errors = [
        calibrated_predictions[label.forecast_id] - label.realized_value
        for label in comparable_oos_rows
    ]
    improvement_ci = _bootstrap_relative_improvement_interval(
        raw_errors, calibrated_errors, seed=seed + 3, resamples=resamples
    )
    relative_improvement = (
        (raw.continuous.mae - calibrated.continuous.mae) / raw.continuous.mae
        if raw.continuous.mae is not None
        and calibrated.continuous.mae is not None
        and raw.continuous.mae
        else None
    )
    if policy.require_oos_improvement_over_raw and (
        calibrated.continuous.mae is None
        or raw.continuous.mae is None
        or calibrated.continuous.mae >= raw.continuous.mae
    ):
        reasons.append("OOS_NOT_BETTER_THAN_RAW")
    if (
        relative_improvement is None
        or relative_improvement < policy.minimum_relative_improvement
    ):
        reasons.append("OOS_IMPROVEMENT_BELOW_THRESHOLD")
    if (
        improvement_ci is None
        or improvement_ci.lower <= policy.minimum_improvement_confidence_lower
    ):
        reasons.append("OOS_IMPROVEMENT_UNCERTAIN")
    naive_errors = [
        naive_predictions[label.forecast_id] - label.realized_value
        for label in comparable_oos_rows
    ]
    naive_improvement_ci = _bootstrap_relative_improvement_interval(
        naive_errors,
        calibrated_errors,
        seed=seed + 4,
        resamples=resamples,
    )
    naive_relative_improvement = (
        (naive.continuous.mae - calibrated.continuous.mae) / naive.continuous.mae
        if naive.continuous.mae is not None
        and calibrated.continuous.mae is not None
        and naive.continuous.mae
        else None
    )
    if (
        naive_relative_improvement is None
        or naive_relative_improvement < policy.minimum_relative_improvement
    ):
        reasons.append("OOS_IMPROVEMENT_BELOW_NAIVE_THRESHOLD")
    if (
        naive_improvement_ci is None
        or naive_improvement_ci.lower <= policy.minimum_improvement_confidence_lower
    ):
        reasons.append("OOS_NAIVE_IMPROVEMENT_UNCERTAIN")
    if policy.require_oos_improvement_over_naive and (
        calibrated.continuous.mae is None
        or naive.continuous.mae is None
        or calibrated.continuous.mae >= naive.continuous.mae
    ):
        reasons.append("OOS_NOT_BETTER_THAN_NAIVE")
    if policy.maximum_absolute_bias is not None and (
        calibrated.continuous.signed_bias is None
        or abs(calibrated.continuous.signed_bias) > policy.maximum_absolute_bias
    ):
        reasons.append("BIAS_GATE_FAILED")
    if policy.minimum_interval_coverage is not None and (
        calibrated.interval is None
        or calibrated.interval.coverage is None
        or calibrated.interval.coverage < policy.minimum_interval_coverage
    ):
        reasons.append("COVERAGE_GATE_FAILED")
    if policy.minimum_interval_coverage is not None:
        coverage_ci = (
            calibrated.interval.coverage_confidence_interval
            if calibrated.interval
            else None
        )
        if (
            coverage_ci is None
            or coverage_ci.lower < policy.minimum_interval_coverage_confidence_lower
        ):
            reasons.append("COVERAGE_CONFIDENCE_GATE_FAILED")
        if any(
            label.interval_confidence != policy.expected_interval_confidence
            for label in oos_rows
            if label.lower_bound is not None and label.upper_bound is not None
        ):
            reasons.append("INTERVAL_CONFIDENCE_MISMATCH")
    fallback_rate = (
        sum(label.provider_fallback for label in split_ids["oos"])
        / len(split_ids["oos"])
        if split_ids["oos"]
        else 1.0
    )
    if fallback_rate > policy.maximum_provider_fallback_rate:
        reasons.append("PROVIDER_FALLBACK_GATE_FAILED")
    missing_calibrated = sum(
        label.forecast_id not in calibrated_predictions for label in oos_rows
    )
    missing_naive = sum(
        label.forecast_id not in naive_predictions for label in oos_rows
    )
    missing_rate = missing_calibrated / len(oos_rows) if oos_rows else 1.0
    naive_missing_rate = missing_naive / len(oos_rows) if oos_rows else 1.0
    if max(missing_rate, naive_missing_rate) > policy.maximum_missing_rate:
        reasons.append("MISSINGNESS_GATE_FAILED")
    abstention_count = missing_calibrated + sum(
        reason.reason in {"no_eligible_label", "missing_value"}
        for reason in split_manifest.excluded
    )
    label_exclusions = label_build_report.excluded
    abstention_count += sum(
        reason.reason in {"no_eligible_label", "missing_value"}
        for reason in label_exclusions
    )
    exclusion_manifest = tuple(label_exclusions) + split_manifest.excluded
    total_forecasts = len(labels) + len(label_exclusions)
    abstention_rate = abstention_count / total_forecasts if total_forecasts else 1.0
    if abstention_rate > policy.maximum_abstention_rate:
        reasons.append("ABSTENTION_GATE_FAILED")
    if policy.maximum_drift is not None and (
        drift is None or drift > policy.maximum_drift
    ):
        reasons.append("DRIFT_GATE_FAILED")
    status: Literal["active", "inactive", "rejected", "expired"] = (
        "inactive" if not labels else ("active" if not reasons else "rejected")
    )
    expires_at = now.astimezone(timezone.utc) + timedelta(days=policy.expiry_days)
    payload = {
        "calibration_id": calibration_id,
        "calibration_version": calibration_version,
        "status": status,
        "target": resolved_target,
        "target_layer": target_layer,
        "metric": metric,
        "model_id": model_id,
        "cohort_id": cohort_id,
        "training_window": training_window,
        "data_snapshot_ids": data_snapshot_ids,
        "feature_contract": feature_contract,
        "label_contract": label_contract,
        "split_manifest_digest": split_manifest.manifest_digest,
        "split_policy_version": split_manifest.policy.split_policy_version,
        "purge_days": split_manifest.policy.purge_days,
        "embargo_days": split_manifest.policy.embargo_days,
        "model_class": model_class,
        "hyperparameters": hyperparameters or {},
        "raw_metrics": raw,
        "calibrated_metrics": calibrated,
        "naive_metrics": naive,
        "sample_counts": {
            "train": sum(row.split == "train" for row in split_manifest.included),
            "validation": sum(
                row.split == "validation" for row in split_manifest.included
            ),
            "oos": len(split_ids["oos"]),
            "excluded": len(split_manifest.excluded),
            "label_build_excluded": len(label_exclusions),
        },
        "cohort_sample_counts": cohort_counts,
        "cohort_metrics": cohort_metrics,
        "missingness_counts": {
            "labels_without_calibrated_prediction": missing_calibrated,
            "labels_without_naive_prediction": missing_naive,
            "excluded_rows": len(split_manifest.excluded),
            "label_build_excluded_rows": len(label_exclusions),
        },
        "abstention_count": abstention_count,
        "label_manifest_digest": label_build_report.manifest_digest,
        "exclusion_manifest": exclusion_manifest,
        "provider_fallback_rate": fallback_rate,
        "improvement_confidence_interval": improvement_ci,
        "naive_improvement_confidence_interval": naive_improvement_ci,
        "confidence_method": "percentile-bootstrap",
        "fallback_policy": "raw-policy-on-gate-failure",
        "owner": owner,
        "review_status": "rejected"
        if status == "rejected"
        else ("approved" if status == "active" else "pending"),
        "created_at": now,
        "expires_at": expires_at,
        "policy_version": policy.policy_version,
        "quality_issue_codes": quality_issue_codes,
        "gate_reasons": tuple(reasons),
        "affects_base_value": False,
    }
    return CalibrationArtifactV1(**payload, artifact_digest=sha256_digest(payload))


def expire_calibration(
    artifact: CalibrationArtifactV1, *, now: datetime
) -> CalibrationArtifactV1:
    if now.tzinfo is None or now.utcoffset() is None:
        raise CalibrationError(
            "TIMEZONE_REQUIRED", "expiry timestamp must include timezone"
        )
    if now < artifact.expires_at or artifact.status != "active":
        return artifact
    payload = artifact.model_dump(exclude={"status", "artifact_digest"})
    payload["status"] = "expired"
    return CalibrationArtifactV1(**payload, artifact_digest=sha256_digest(payload))
