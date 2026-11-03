import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fundamental_service.calibration import (
    CalibrationError,
    CalibrationLabelV1,
    LabelBuildReportV1,
    ForecastObservationV1,
    PublishedOutcomeV1,
    PromotionPolicyV1,
    SplitPolicyV1,
    build_point_in_time_labels,
    build_split_manifest,
    calculate_metric_bundle,
    evaluate_calibration,
    expire_calibration,
)


UTC = timezone.utc


def dt(day: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day - 1)


def forecast(
    forecast_id: str,
    issuer: str,
    day: int,
    value: float = 10.0,
    *,
    evidence_class: str = "calibration",
    industry_cohort: str = "unassigned",
    lower_bound: float | None = None,
    upper_bound: float | None = None,
    provider_fallback: bool = False,
    interval_confidence: float = 0.8,
    target_period_start_day: int = 2,
    target_period_end_day: int = 3,
):
    return ForecastObservationV1(
        forecast_id=forecast_id,
        issuer_id=issuer,
        target="revenue_growth",
        decision_timestamp=dt(day),
        target_period_start=dt(target_period_start_day),
        target_period_end=dt(target_period_end_day),
        forecast_value=value,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        provider_fallback=provider_fallback,
        evidence_class=evidence_class,
        industry_cohort=industry_cohort,
        interval_confidence=interval_confidence,
        source_snapshot_id=f"snapshot-{forecast_id}",
    )


def outcome(
    outcome_id: str,
    issuer: str,
    day: int,
    value: float,
    restatement: bool = False,
    *,
    period_end_day: int = 3,
    source_snapshot_id: str | None = None,
):
    return PublishedOutcomeV1(
        outcome_id=outcome_id,
        issuer_id=issuer,
        target="revenue_growth",
        period_end=dt(period_end_day),
        published_at=dt(day),
        value=value,
        source_snapshot_id=source_snapshot_id or f"snapshot-{outcome_id}",
        is_restatement=restatement,
    )


def test_point_in_time_label_keeps_first_publication_and_restated_diagnostic():
    report = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 1),),
        (outcome("o1", "issuer-1", 4, 11), outcome("o2", "issuer-1", 5, 99, True)),
    )
    assert report.labels[0].realized_value == 11
    assert report.labels[0].outcome_id == "o1"
    assert report.restatement_diagnostics == {"f1": ("o2",)}


def test_label_requires_later_publication_and_does_not_look_ahead():
    report = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 10),),
        (outcome("o1", "issuer-1", 5, 11),),
    )
    assert report.labels == ()
    assert report.excluded[0].reason == "no_eligible_label"


def test_split_manifest_is_chronological_purged_and_grouped():
    labels = build_point_in_time_labels(
        (
            forecast("train", "issuer-1", 1),
            forecast("validation", "issuer-2", 10),
            forecast("oos", "issuer-3", 20),
        ),
        (
            outcome("train-outcome", "issuer-1", 4, 10),
            outcome("validation-outcome", "issuer-2", 13, 10),
            outcome("oos-outcome", "issuer-3", 23, 10),
        ),
    ).labels
    manifest = build_split_manifest(
        labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(8),
            validation_end=dt(18),
            oos_end=dt(30),
            purge_days=0,
            embargo_days=0,
        ),
    )
    assert [row.split for row in manifest.included] == ["train", "validation", "oos"]
    assert manifest.manifest_digest


def test_metrics_report_raw_calibrated_naive_and_intervals():
    labels = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 1, 10),),
        (outcome("o1", "issuer-1", 4, 11),),
    ).labels
    metrics = calculate_metric_bundle(
        labels, {"f1": 11}, {"f1": 13}, seed=7, resamples=50
    )
    assert metrics.continuous.mae == 0
    assert metrics.continuous.confidence_interval is not None


def test_failed_gates_reject_calibration_without_changing_base_value():
    label_report = build_point_in_time_labels(
        tuple(forecast(f"f{i}", f"issuer-{i}", i, 10) for i in range(1, 4)),
        tuple(outcome(f"o{i}", f"issuer-{i}", i + 3, 30) for i in range(1, 4)),
    )
    labels = label_report.labels
    split = build_split_manifest(
        labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(3),
            validation_end=dt(5),
            oos_end=dt(30),
            purge_days=0,
            embargo_days=0,
            group_by_issuer=False,
        ),
    )
    artifact = evaluate_calibration(
        labels,
        split,
        label_build_report=label_report,
        calibrated_predictions={label.forecast_id: 10 for label in labels},
        naive_predictions={label.forecast_id: 20 for label in labels},
        policy=PromotionPolicyV1(
            policy_version="policy-v1",
            minimum_oos_samples=10,
            expiry_days=30,
        ),
        calibration_id="calibration-1",
        calibration_version="calibration-v1",
        target_layer="forecast",
        metric="mae",
        model_id="fcff_dcf",
        cohort_id="cohort-1",
        data_snapshot_ids=("snapshot-1",),
        feature_contract="features-v1",
        label_contract="labels-v1",
        model_class="identity",
        owner="reviewer",
        now=dt(30),
        training_window=(dt(1), dt(3)),
    )
    assert artifact.status == "rejected"
    assert "INSUFFICIENT_OOS_SAMPLE" in artifact.gate_reasons
    assert artifact.affects_base_value is False
    assert expire_calibration(artifact, now=dt(90)).status == "rejected"


def test_expiry_marks_active_artifact_expired():
    label_report = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 20, 12), forecast("f2", "issuer-2", 20, 12)),
        (outcome("o1", "issuer-1", 23, 10), outcome("o2", "issuer-2", 23, 10)),
    )
    labels = label_report.labels
    split = build_split_manifest(
        labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(1),
            validation_end=dt(2),
            oos_end=dt(30),
            purge_days=0,
            embargo_days=0,
            group_by_issuer=False,
        ),
    )
    artifact = evaluate_calibration(
        labels,
        split,
        label_build_report=label_report,
        calibrated_predictions={"f1": 10, "f2": 10},
        naive_predictions={"f1": 20, "f2": 20},
        policy=PromotionPolicyV1(
            policy_version="policy-v1",
            minimum_oos_samples=2,
            minimum_cohort_samples=1,
            minimum_interval_coverage=None,
            expiry_days=1,
        ),
        calibration_id="calibration-2",
        calibration_version="calibration-v1",
        target_layer="forecast",
        metric="mae",
        model_id="fcff_dcf",
        cohort_id="cohort-1",
        data_snapshot_ids=("snapshot-1",),
        feature_contract="features-v1",
        label_contract="labels-v1",
        model_class="identity",
        owner="reviewer",
        now=dt(10),
        training_window=(dt(1), dt(3)),
    )
    assert artifact.status == "active"
    assert expire_calibration(artifact, now=dt(12)).status == "expired"
    with pytest.raises(CalibrationError, match="expiry timestamp"):
        expire_calibration(artifact, now=datetime(2026, 1, 12))


def test_invalid_interval_is_rejected():
    with pytest.raises(ValueError):
        ForecastObservationV1(
            forecast_id="bad",
            issuer_id="issuer",
            target="metric",
            decision_timestamp=dt(1),
            target_period_start=dt(2),
            target_period_end=dt(3),
            forecast_value=5,
            lower_bound=6,
            upper_bound=4,
            source_snapshot_id="snapshot",
        )


def test_engineering_cohort_is_excluded_from_calibration_labels():
    report = build_point_in_time_labels(
        (
            forecast(
                "engineering-1",
                "issuer-1",
                1,
                evidence_class="engineering",
            ),
        ),
        (outcome("outcome-1", "issuer-1", 4, 11),),
    )
    assert report.labels == ()
    assert report.excluded[0].reason == "engineering_cohort"


def test_label_build_report_rejects_duplicate_forecast_ids():
    report = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 1),),
        (outcome("o1", "issuer-1", 4, 11),),
    )
    with pytest.raises(ValueError, match="forecast IDs must be unique"):
        LabelBuildReportV1(
            labels=(report.labels[0], report.labels[0]),
            excluded=report.excluded,
            restatement_diagnostics=report.restatement_diagnostics,
            label_rule_version=report.label_rule_version,
            manifest_digest="0" * 64,
        )


def test_split_purge_does_not_assign_issuer_before_exclusion():
    labels = build_point_in_time_labels(
        (
            forecast(
                "purged",
                "issuer-1",
                1,
                target_period_start_day=2,
                target_period_end_day=10,
            ),
            forecast("oos", "issuer-1", 20),
        ),
        (
            outcome("purged-outcome", "issuer-1", 11, 10, period_end_day=10),
            outcome("oos-outcome", "issuer-1", 23, 10),
        ),
    ).labels
    manifest = build_split_manifest(
        labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(5),
            validation_end=dt(15),
            oos_end=dt(30),
            purge_days=1,
            embargo_days=0,
        ),
    )
    assert [row.forecast_id for row in manifest.included] == ["oos"]
    assert any(row.reason == "overlap_purged" for row in manifest.excluded)


def test_real_sec_snapshot_hash_is_carried_into_label_provenance():
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    manifest = json.loads((fixture_root / "capture_manifest.json").read_text())
    filing_hash = next(
        record["sha256"]
        for record in manifest["sources"]
        if record["source_id"] == "sec-filing" and record["form"] == "10-K"
    )
    labels = build_point_in_time_labels(
        (forecast("f1", "0000320193", 1),),
        (
            outcome(
                "apple-revenue-2024",
                "0000320193",
                100,
                391035000000,
                source_snapshot_id=filing_hash,
            ),
        ),
    ).labels
    assert labels[0].source_snapshot_id == filing_hash
    assert labels[0].realized_value == 391035000000


def _large_oos_fixture():
    forecasts = tuple(
        forecast(
            f"f{i}",
            f"issuer-{i}",
            20 + i,
            10,
            industry_cohort="software" if i < 15 else "industrial",
            lower_bound=0,
            upper_bound=30,
        )
        for i in range(30)
    )
    outcomes = tuple(outcome(f"o{i}", f"issuer-{i}", 23 + i, 20) for i in range(30))
    label_report = build_point_in_time_labels(forecasts, outcomes)
    labels = label_report.labels
    split = build_split_manifest(
        labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(5),
            validation_end=dt(15),
            oos_end=dt(80),
            purge_days=0,
            embargo_days=0,
        ),
    )
    return label_report, split


def test_v1_promotion_requires_oos_cohorts_improvement_and_interval_coverage():
    label_report, split = _large_oos_fixture()
    labels = label_report.labels
    artifact = evaluate_calibration(
        labels,
        split,
        label_build_report=label_report,
        calibrated_predictions={label.forecast_id: 20 for label in labels},
        naive_predictions={label.forecast_id: 15 for label in labels},
        policy=PromotionPolicyV1(
            policy_version="v1",
            expiry_days=30,
        ),
        calibration_id="calibration-large",
        calibration_version="v1",
        target_layer="forecast",
        metric="mae",
        model_id="fcff_dcf",
        cohort_id="software-industrial",
        data_snapshot_ids=("sec-snapshot-a14d",),
        feature_contract="features-v1",
        label_contract="labels-v1",
        model_class="identity",
        owner="reviewer",
        now=dt(100),
        training_window=(dt(1), dt(4)),
        resamples=200,
    )
    assert artifact.status == "active"
    assert artifact.review_status == "approved"
    assert artifact.target == "revenue_growth"
    assert artifact.sample_counts["oos"] == 30
    assert artifact.cohort_sample_counts == {"software": 15, "industrial": 15}
    assert artifact.calibrated_metrics.interval is not None
    assert artifact.calibrated_metrics.interval.coverage == 1
    assert (
        artifact.calibrated_metrics.interval.coverage_confidence_interval.lower >= 0.7
    )
    assert artifact.improvement_confidence_interval.lower > 0
    assert artifact.naive_improvement_confidence_interval.lower > 0
    assert artifact.affects_base_value is False


def test_missing_prediction_is_rejected_and_recorded_in_manifest():
    label_report, split = _large_oos_fixture()
    labels = label_report.labels
    calibrated = {label.forecast_id: 20 for label in labels}
    calibrated.pop("f0")
    artifact = evaluate_calibration(
        labels,
        split,
        label_build_report=label_report,
        calibrated_predictions=calibrated,
        naive_predictions={label.forecast_id: 15 for label in labels},
        policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
        calibration_id="calibration-missing",
        calibration_version="v1",
        target_layer="forecast",
        metric="mae",
        model_id="fcff_dcf",
        cohort_id="software-industrial",
        data_snapshot_ids=("sec-snapshot-a14d",),
        feature_contract="features-v1",
        label_contract="labels-v1",
        model_class="identity",
        owner="reviewer",
        now=dt(100),
        training_window=(dt(1), dt(4)),
        resamples=200,
    )
    assert artifact.status == "rejected"
    assert "MISSINGNESS_GATE_FAILED" in artifact.gate_reasons
    assert "INSUFFICIENT_OOS_SAMPLE" in artifact.gate_reasons
    assert artifact.missingness_counts["labels_without_calibrated_prediction"] == 1
    assert artifact.raw_metrics.continuous.sample_count == 29
    assert artifact.calibrated_metrics.continuous.sample_count == 29
    assert artifact.review_status == "rejected"


def test_label_build_exclusions_are_carried_into_abstention_manifest():
    label_report = build_point_in_time_labels(
        (
            forecast("eligible", "issuer-1", 1),
            forecast("unlabeled", "issuer-2", 1),
        ),
        (outcome("eligible-outcome", "issuer-1", 4, 11),),
    )
    split = build_split_manifest(
        label_report.labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(1),
            validation_end=dt(2),
            oos_end=dt(30),
            purge_days=0,
            embargo_days=0,
            group_by_issuer=False,
        ),
    )
    artifact = evaluate_calibration(
        label_report.labels,
        split,
        label_build_report=label_report,
        calibrated_predictions={"eligible": 11},
        naive_predictions={"eligible": 12},
        policy=PromotionPolicyV1(
            policy_version="v1",
            minimum_oos_samples=1,
            minimum_cohort_samples=1,
            minimum_interval_coverage=None,
            maximum_abstention_rate=0,
            expiry_days=30,
        ),
        calibration_id="calibration-exclusion",
        calibration_version="v1",
        target_layer="forecast",
        metric="mae",
        model_id="fcff_dcf",
        cohort_id="software",
        data_snapshot_ids=("snapshot-eligible",),
        feature_contract="features-v1",
        label_contract="labels-v1",
        model_class="identity",
        owner="reviewer",
        now=dt(30),
        training_window=(dt(1), dt(2)),
    )
    assert artifact.status == "rejected"
    assert artifact.label_manifest_digest == label_report.manifest_digest
    assert artifact.abstention_count == 1
    assert "ABSTENTION_GATE_FAILED" in artifact.gate_reasons
    assert artifact.exclusion_manifest[0].forecast_id == "unlabeled"


def test_label_cannot_be_available_before_its_forecast_decision():
    with pytest.raises(ValueError, match="published after"):
        CalibrationLabelV1(
            forecast_id="f1",
            issuer_id="issuer-1",
            target="revenue_growth",
            decision_timestamp=dt(10),
            target_period_start=dt(2),
            target_period_end=dt(3),
            forecast_value=10,
            realized_value=11,
            label_available_at=dt(9),
            source_snapshot_id="outcome-snapshot",
            forecast_source_snapshot_id="forecast-snapshot",
            outcome_id="o1",
        )


def test_split_manifest_mismatch_is_a_stable_calibration_error():
    first_report = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 20),),
        (outcome("o1", "issuer-1", 23, 10),),
    )
    second_report = build_point_in_time_labels(
        (forecast("f2", "issuer-2", 20),),
        (outcome("o2", "issuer-2", 23, 10),),
    )
    split = build_split_manifest(
        second_report.labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(5),
            validation_end=dt(15),
            oos_end=dt(30),
            purge_days=0,
            embargo_days=0,
        ),
    )
    with pytest.raises(CalibrationError, match="split manifest") as error:
        evaluate_calibration(
            first_report.labels,
            split,
            label_build_report=first_report,
            calibrated_predictions={"f1": 10},
            naive_predictions={"f1": 11},
            policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
            calibration_id="mismatch",
            calibration_version="v1",
            target_layer="forecast",
            metric="mae",
            model_id="fcff_dcf",
            cohort_id="software",
            data_snapshot_ids=("snapshot",),
            feature_contract="features-v1",
            label_contract="labels-v1",
            model_class="identity",
            owner="reviewer",
            now=dt(30),
            training_window=(dt(1), dt(4)),
        )
    assert error.value.code == "SPLIT_LABEL_MISMATCH"


def test_label_report_binds_full_payload_not_only_forecast_ids():
    label_report = build_point_in_time_labels(
        (forecast("f1", "issuer-1", 20),),
        (outcome("o1", "issuer-1", 23, 10),),
    )
    altered_label = label_report.labels[0].model_copy(update={"realized_value": 99})
    split = build_split_manifest(
        label_report.labels,
        SplitPolicyV1(
            split_policy_version="split-v1",
            train_end=dt(5),
            validation_end=dt(15),
            oos_end=dt(30),
            purge_days=0,
            embargo_days=0,
        ),
    )
    with pytest.raises(CalibrationError, match="complete labels") as error:
        evaluate_calibration(
            (altered_label,),
            split,
            label_build_report=label_report,
            calibrated_predictions={"f1": 10},
            naive_predictions={"f1": 11},
            policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
            calibration_id="tampered",
            calibration_version="v1",
            target_layer="forecast",
            metric="mae",
            model_id="fcff_dcf",
            cohort_id="software",
            data_snapshot_ids=("snapshot",),
            feature_contract="features-v1",
            label_contract="labels-v1",
            model_class="identity",
            owner="reviewer",
            now=dt(30),
            training_window=(dt(1), dt(4)),
        )
    assert error.value.code == "LABEL_REPORT_MISMATCH"


def test_split_manifest_requires_complete_label_coverage_and_matching_issuer():
    label_report, split = _large_oos_fixture()
    incomplete = split.model_copy(update={"included": split.included[:-1]})
    with pytest.raises(CalibrationError, match="cover each evaluated label") as error:
        evaluate_calibration(
            label_report.labels,
            incomplete,
            label_build_report=label_report,
            calibrated_predictions={
                label.forecast_id: 20 for label in label_report.labels
            },
            naive_predictions={label.forecast_id: 15 for label in label_report.labels},
            policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
            calibration_id="incomplete-split",
            calibration_version="v1",
            target_layer="forecast",
            metric="mae",
            model_id="fcff_dcf",
            cohort_id="software-industrial",
            data_snapshot_ids=("snapshot",),
            feature_contract="features-v1",
            label_contract="labels-v1",
            model_class="identity",
            owner="reviewer",
            now=dt(100),
            training_window=(dt(1), dt(4)),
        )
    assert error.value.code == "SPLIT_LABEL_MISMATCH"

    wrong_issuer = split.included[0].model_copy(update={"issuer_id": "wrong-issuer"})
    malformed = split.model_copy(
        update={"included": (wrong_issuer, *split.included[1:])}
    )
    with pytest.raises(CalibrationError, match="issuer") as error:
        evaluate_calibration(
            label_report.labels,
            malformed,
            label_build_report=label_report,
            calibrated_predictions={
                label.forecast_id: 20 for label in label_report.labels
            },
            naive_predictions={label.forecast_id: 15 for label in label_report.labels},
            policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
            calibration_id="issuer-split",
            calibration_version="v1",
            target_layer="forecast",
            metric="mae",
            model_id="fcff_dcf",
            cohort_id="software-industrial",
            data_snapshot_ids=("snapshot",),
            feature_contract="features-v1",
            label_contract="labels-v1",
            model_class="identity",
            owner="reviewer",
            now=dt(100),
            training_window=(dt(1), dt(4)),
        )
    assert error.value.code == "SPLIT_LABEL_MISMATCH"


def test_market_outcome_requires_separate_signal_contract():
    label_report, split = _large_oos_fixture()
    labels = label_report.labels
    with pytest.raises(CalibrationError, match="separate signal-evaluation contract"):
        evaluate_calibration(
            labels,
            split,
            label_build_report=label_report,
            calibrated_predictions={},
            naive_predictions={},
            policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
            calibration_id="market",
            calibration_version="v1",
            target_layer="market_outcome",
            metric="mae",
            model_id="fcff_dcf",
            cohort_id="market",
            data_snapshot_ids=("market-snapshot",),
            feature_contract="features-v1",
            label_contract="labels-v1",
            model_class="identity",
            owner="reviewer",
            now=dt(100),
            training_window=(dt(1), dt(4)),
        )


def test_no_labels_create_explicit_inactive_artifact():
    label_report = build_point_in_time_labels((), ())
    policy = SplitPolicyV1(
        split_policy_version="split-v1",
        train_end=dt(5),
        validation_end=dt(15),
        oos_end=dt(30),
        purge_days=0,
        embargo_days=0,
    )
    artifact = evaluate_calibration(
        (),
        build_split_manifest((), policy),
        label_build_report=label_report,
        calibrated_predictions={},
        naive_predictions={},
        policy=PromotionPolicyV1(policy_version="v1", expiry_days=30),
        calibration_id="inactive",
        calibration_version="v1",
        target_layer="forecast",
        target="revenue_growth",
        metric="mae",
        model_id="fcff_dcf",
        cohort_id="software",
        data_snapshot_ids=("sec-snapshot",),
        feature_contract="features-v1",
        label_contract="labels-v1",
        model_class="identity",
        owner="reviewer",
        now=dt(100),
        training_window=(dt(1), dt(4)),
    )
    assert artifact.status == "inactive"
    assert artifact.review_status == "pending"
    assert "NO_OOS_EVIDENCE" in artifact.gate_reasons
