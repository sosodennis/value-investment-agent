"""Real composer/calculator execution on synthetic release-bound fixtures only."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

from fundamental_service.application import FundamentalApplication
from fundamental_service.contracts import IdentityV1
from fundamental_service.data_releases import DataReleaseManifestV1, MappingRefV1
from fundamental_service.history_forecast_replay import (
    HistoryEvidenceProtocolV1,
    HistoryReplayPlanV1,
    ReplayModelPinV1,
    ReplayOriginV1,
    ReplayReleasePinV1,
    _summary,
    run_history_replay,
    write_history_replay,
)
from fundamental_service.history_sufficiency_report import Filing
from fundamental_service import history_forecast_replay_cli as cli
from fundamental_service.facts import (
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
)
from fundamental_service.operations import (
    OperationalMetrics,
    OperationsConfig,
    ServiceError,
)
from fundamental_service.policies import (
    PolicyRegistry,
    initial_model_specs,
    initial_policy_records,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import (
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotError,
)
from fundamental_service.uncertainty import UncertaintyReportV1
from test_postgres_metadata import _snapshot
from test_valuation_preparation import _facts
from test_valuation_preparation_integration import _complete_manifest


def _fixture(
    tmp_path: Path,
    *,
    label_mode: str = "complete",
    mapping_mode: str = "reviewed",
    missing_forecast_field: str | None = None,
) -> tuple[FundamentalApplication, HistoryReplayPlanV1]:
    identity = IdentityV1(
        issuer_id="CIK1",
        issuer_name="Synthetic Co",
        domicile="US",
        reporting_basis="us-gaap",
        security_id="COMMON",
        share_class="common",
        currency="USD",
    )
    decision = Filing(
        "CIK1",
        "0000000001-26-000001",
        "10-K",
        date(2025, 12, 31),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    following = Filing(
        "CIK1",
        "0000000001-27-000001",
        "10-K",
        date(2026, 12, 31),
        datetime(2027, 3, 1, tzinfo=UTC),
    )
    amendment = Filing(
        "CIK1",
        "0000000001-27-000002",
        "10-K/A",
        date(2026, 12, 31),
        datetime(2027, 4, 1, tzinfo=UTC),
    )
    facts = tuple(
        fact.model_copy(
            update={
                "captured_at": decision.accepted_at,
                "accession_number": decision.accession,
                "source": fact.source.model_copy(
                    update={
                        "available_at": fact.available_at,
                        "captured_at": decision.accepted_at,
                    }
                ),
            }
        )
        for fact in _facts()
    )
    labels = tuple(
        fact.model_copy(
            update={
                "fact_id": f"label-{fact.fact_id}",
                "period_start": fact.period_start.replace(
                    year=fact.period_start.year + 1
                )
                if fact.period_start
                else None,
                "period_end": fact.period_end.replace(year=fact.period_end.year + 1),
                "instant": fact.instant.replace(year=fact.instant.year + 1)
                if fact.instant
                else None,
                "value": fact.value + Decimal(10)
                if fact.normalized_field == "revenue"
                else fact.value,
                "available_at": following.accepted_at,
                "captured_at": following.accepted_at,
                "accession_number": following.accession,
                "source": fact.source.model_copy(
                    update={
                        "available_at": following.accepted_at,
                        "captured_at": following.accepted_at,
                    }
                ),
                "context": fact.context.model_copy(
                    update={
                        "start_date": fact.period_start.replace(
                            year=fact.period_start.year + 1
                        )
                        if fact.period_start
                        else None,
                        "end_date": fact.period_end.replace(
                            year=fact.period_end.year + 1
                        )
                        if fact.period_start
                        else None,
                        "instant": fact.instant.replace(year=fact.instant.year + 1)
                        if fact.instant
                        else None,
                    }
                ),
            }
        )
        for fact in facts
    )
    if label_mode == "incomplete":
        labels = tuple(
            fact for fact in labels if fact.normalized_field != "operating_income"
        )
    elif label_mode == "restated":
        labels = tuple(
            fact.model_copy(
                update={"accession_number": amendment.accession, "is_amendment": True}
            )
            for fact in labels
        )
    mappings = {
        fact.normalized_field: CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=f"mapping-{fact.normalized_field}",
            source_concept=fact.concept,
            normalized_field=fact.normalized_field,
            mapping_version="fixture-reviewed-mapping-v2",
            confidence="high",
            evidence_refs=("a" * 64,),
            reviewer="fixture-independent-reviewer",
            reviewed_at=datetime(2026, 11, 10, tzinfo=UTC),
            status="approved",
        )
        for fact in facts
    }
    facts = tuple(
        fact.model_copy(
            update={"mapping_decision_id": mappings[fact.normalized_field].decision_id}
        )
        for fact in facts
    )
    labels = tuple(
        fact.model_copy(
            update={"mapping_decision_id": mappings[fact.normalized_field].decision_id}
        )
        for fact in labels
    )
    facts = tuple(
        fact for fact in facts if fact.normalized_field != missing_forecast_field
    )
    if mapping_mode == "unbound":
        facts = tuple(
            fact.model_copy(update={"mapping_decision_id": "not-declared"})
            for fact in facts
        )
    elif mapping_mode == "label-unbound":
        labels = tuple(
            fact.model_copy(update={"mapping_decision_id": "not-declared"})
            for fact in labels
        )
    snapshots = {
        "forecast": _snapshot(
            "replay-forecast",
            identity=identity,
            valuation_timestamp=decision.accepted_at,
            policy_version="pit-v1",
        ),
        "label": _snapshot(
            "replay-label",
            identity=identity,
            valuation_timestamp=following.accepted_at,
            policy_version="pit-v1",
        ),
    }
    manifests: tuple[DataReleaseManifestV1, ...] = (
        _complete_manifest(snapshots["forecast"], facts),
        _complete_manifest(snapshots["label"], labels),
    )
    refs = tuple(
        MappingRefV1(
            mapping_id=mapping.decision_id, mapping_digest=sha256_digest(mapping)
        )
        for _, mapping in sorted(mappings.items())
    )
    bound_manifests = []
    for manifest in manifests:
        payload = {**manifest.model_dump(), "mapping_refs": refs}
        payload["manifest_digest"] = sha256_digest(
            {k: v for k, v in payload.items() if k != "manifest_digest"}
        )
        bound_manifests.append(DataReleaseManifestV1.model_validate(payload))
    manifests = tuple(bound_manifests)

    class Metadata:
        def get_mapping(self, mapping_id: str) -> CanonicalMappingV1:
            if mapping_mode == "missing":
                raise SnapshotError("MAPPING_NOT_FOUND", "fixture mapping missing")
            mapping = next(
                mapping
                for mapping in mappings.values()
                if mapping.decision_id == mapping_id
            )
            return (
                mapping.model_copy(update={"mapping_version": "tampered"})
                if mapping_mode == "tampered"
                else mapping
            )

        def get_data_release_manifest(
            self, digest: str
        ) -> DataReleaseManifestV1 | None:
            return next(
                (
                    manifest
                    for manifest in manifests
                    if manifest.manifest_digest == digest
                ),
                None,
            )

    snapshot_repository = FilesystemSnapshotRepository(tmp_path / "snapshots")
    fact_repository = FilesystemCanonicalFactRepository(tmp_path / "facts")
    for snapshot in snapshots.values():
        snapshot_repository.publish(snapshot)
    for fact in (*facts, *labels):
        fact_repository.publish(fact)
    app = FundamentalApplication(
        snapshot_repository=snapshot_repository,
        fact_repository=fact_repository,
        metadata_store=Metadata(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        content_store=FilesystemContentStore(tmp_path / "content"),
        config=OperationsConfig.testing(),
        metrics=OperationalMetrics(),
        policy_registry=PolicyRegistry(initial_model_specs(), initial_policy_records()),
    )
    policy = initial_policy_records()[0]
    model = ReplayModelPinV1(
        model_id="fcff_dcf",
        model_version=policy.model_version,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
    )
    pins = tuple(
        ReplayReleasePinV1(
            snapshot_id=snapshot.snapshot_id,
            snapshot_manifest_digest=snapshot.manifest_digest,
            data_release_manifest_digest=manifest.manifest_digest,
            source_policy_version=snapshot.policy_version,
        )
        for snapshot, manifest in zip(snapshots.values(), manifests, strict=True)
    )
    origin = ReplayOriginV1(
        decision=decision,
        filings=(amendment, following, decision),
        forecast_release=pins[0],
        label_release=pins[1],
    )
    plan = HistoryReplayPlanV1(
        cohort_digest="a" * 64,
        mapping_version="fixture-reviewed-mapping-v2",
        runtime={"commit_sha": "a" * 40, "evidence_class": "engineering"},
        models=(model,),
        evidence_class="engineering",
        origins=(origin,),
    )
    return app, plan


def _rows(
    artifacts: dict[str, dict[str, object]], kind: str
) -> list[dict[str, object]]:
    rows = artifacts[kind]["rows"]
    assert isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
    return rows


def test_real_composer_nodes_and_first_original_labels_replay_unchanged(
    tmp_path: Path,
) -> None:
    app, plan = _fixture(tmp_path)
    first = run_history_replay(app, plan)
    forecast = _rows(first, "forecast")[0]
    assert forecast["status"] == "provisional", forecast
    assert first["report"]["composer_invocations"] == 1
    calculation = forecast["calculation"]
    assert isinstance(calculation, UncertaintyReportV1)
    assert forecast["targets"] == {
        "revenue": next(
            node.value for node in calculation.base.nodes if node.node_id == "revenue_1"
        ),
        "fcff": next(
            node.value for node in calculation.base.nodes if node.node_id == "fcff_1"
        ),
    }
    label = _rows(first, "label")[0]
    assert label["status"] == "complete", label
    encoded_label = json.loads(canonical_bytes(label))
    assert encoded_label["first_subsequent_original"]["form"] == "10-K"
    assert Decimal(encoded_label["targets"]["revenue"]) == Decimal(150)
    assert Decimal(encoded_label["targets"]["fcff"]) == Decimal("16.4")
    original_artifacts = {
        path: path.read_bytes()
        for path in (tmp_path / "artifacts").rglob("*")
        if path.is_file()
    }
    writes = write_history_replay(first, tmp_path)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*.gz")
    }
    second = run_history_replay(app, plan)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert {
        path: path.read_bytes()
        for path in (tmp_path / "artifacts").rglob("*")
        if path.is_file()
    } == original_artifacts
    assert all(
        not result["wrote"]
        for result in write_history_replay(second, tmp_path).values()
    )
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*.gz")
    }
    assert first["report"]["supported_history_threshold"] is None
    assert first["report"]["status"] == "engineering_only"
    summary = first["report"]["models"]["fcff_dcf"]
    assert summary["empirical_status"] == "empirical_underpowered"
    assert summary["threshold_decision"] == "engineering_only"
    assert summary["paired_complete_independent_issuers"] == 1
    history = summary["history_length_comparison"]
    assert history["cohort_origins"] == 1
    assert sum(row["selected_origins"] for row in history["strata"]) == 1
    measured = [row for row in history["strata"] if row["selected_origins"]]
    assert len(measured) == 1 and measured[0]["complete_history_years"] == 5
    assert measured[0]["targets"] == summary["targets"]
    assert writes["report"]["sha256"] == sha256_digest(first["report"])


@pytest.mark.parametrize("label_mode", ["incomplete", "restated"])
def test_incomplete_original_labels_cannot_be_replaced_by_amendments(
    tmp_path: Path,
    label_mode: str,
) -> None:
    app, plan = _fixture(tmp_path, label_mode=label_mode)
    result = run_history_replay(app, plan)
    label = json.loads(canonical_bytes(_rows(result, "label")[0]))
    assert label["status"] == "incomplete"
    assert "fcff" not in label["targets"]
    if label_mode == "incomplete":
        assert label["targets"]["revenue"] == "150"
    else:
        assert label["targets"] == {} and label["excluded_label_fact_ids"]
    summary = json.loads(canonical_bytes(result["report"]))["models"]["fcff_dcf"]
    assert summary["forecast_coverage"] == 1 and summary["complete_labels"] == 0
    assert summary["targets"]["fcff"]["independent_issuer_count"] == 0


def test_forecasts_finish_before_labels_and_input_order_is_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, plan = _fixture(tmp_path)
    origin = plan.origins[0]
    prior_decision = Filing(
        "CIK2",
        "0000000002-16-000001",
        "10-K",
        date(2015, 12, 31),
        datetime(2016, 3, 1, tzinfo=UTC),
    )
    missing = ReplayOriginV1(decision=prior_decision, filings=(prior_decision,))
    calls: list[tuple[str, str]] = []
    read = FundamentalApplication.read_valuation_evidence
    prepare = FundamentalApplication.prepare_valuation

    def record_read(self, request):
        calls.append(("read", request.snapshot_id))
        return read(self, request)

    def record_prepare(self, request):
        calls.append(("prepare", request.snapshot_id))
        return prepare(self, request)

    monkeypatch.setattr(FundamentalApplication, "read_valuation_evidence", record_read)
    monkeypatch.setattr(FundamentalApplication, "prepare_valuation", record_prepare)
    first = run_history_replay(
        app, plan.model_copy(update={"origins": (origin, missing)})
    )
    assert _rows(first, "forecast")[0]["issuer_id"] == "CIK2"
    assert origin.label_release is not None
    first_label_read = next(
        index
        for index, call in enumerate(calls)
        if call == ("read", origin.label_release.snapshot_id)
    )
    assert all(
        index < first_label_read
        for index, call in enumerate(calls)
        if call[0] == "prepare"
    )
    shuffled = origin.model_copy(update={"filings": tuple(reversed(origin.filings))})
    second = run_history_replay(
        app, plan.model_copy(update={"origins": (missing, shuffled)})
    )
    assert canonical_bytes(first) == canonical_bytes(second)


def test_second_model_abstention_is_retained_separately(tmp_path: Path) -> None:
    app, plan = _fixture(tmp_path)
    policy = initial_policy_records()[1]
    transition = ReplayModelPinV1(
        model_id="transition_fcff_dcf",
        model_version=policy.model_version,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
    )
    result = run_history_replay(
        app, plan.model_copy(update={"models": (transition, *plan.models)})
    )
    summaries = json.loads(canonical_bytes(result["report"]))["models"]
    assert summaries["fcff_dcf"]["forecast_coverage"] == 1
    assert summaries["transition_fcff_dcf"]["forecast_coverage"] == 0
    assert summaries["transition_fcff_dcf"]["selected_origins"] == 1
    assert len(_rows(result, "forecast")) == len(_rows(result, "label")) == 2


def test_missing_release_and_label_are_retained_in_denominators(tmp_path: Path) -> None:
    app, plan = _fixture(tmp_path)
    origin = plan.origins[0].model_copy(
        update={"forecast_release": None, "label_release": None}
    )
    result = run_history_replay(app, plan.model_copy(update={"origins": (origin,)}))
    assert result["report"]["composer_invocations"] == 0
    assert _rows(result, "forecast")[0]["issue_codes"] == (
        "REPLAY_FORECAST_RELEASE_UNAVAILABLE",
    )
    assert _rows(result, "label")[0]["issue_codes"] == (
        "REPLAY_LABEL_RELEASE_UNAVAILABLE",
    )
    summary = json.loads(canonical_bytes(result["report"]))["models"]["fcff_dcf"]
    assert summary["selected_origins"] == summary["selected_independent_issuers"] == 1
    assert summary["forecast_coverage"] == 0
    assert summary["targets"]["fcff"]["mean_absolute_error"] is None
    assert summary["execution_status"] == "blocked"
    assert summary["empirical_status"] == "not_measured"
    unknown = summary["history_length_comparison"]["strata"][-1]
    assert unknown["complete_history_years"] is None
    assert unknown["selected_origins"] == 1
    assert unknown["forecast_issue_counts"] == {
        "REPLAY_FORECAST_RELEASE_UNAVAILABLE": 1
    }


@pytest.mark.parametrize("defect", ["snapshot", "policy", "mapping"])
def test_mismatched_pins_abstain_without_scoring(defect: str, tmp_path: Path) -> None:
    app, plan = _fixture(tmp_path)
    if defect == "snapshot":
        origin = plan.origins[0]
        assert origin.forecast_release is not None
        pin = origin.forecast_release.model_copy(
            update={"snapshot_manifest_digest": "b" * 64}
        )
        plan = plan.model_copy(
            update={"origins": (origin.model_copy(update={"forecast_release": pin}),)}
        )
    elif defect == "policy":
        plan = plan.model_copy(
            update={
                "models": (
                    plan.models[0].model_copy(update={"policy_digest": "b" * 64}),
                )
            }
        )
    else:
        plan = plan.model_copy(update={"mapping_version": "wrong-version"})
    row = _rows(run_history_replay(app, plan), "forecast")[0]
    assert row["status"] == "abstain" and row["targets"] == {}
    assert json.loads(canonical_bytes(row))["service_failure"]["code"].endswith(
        "PIN_MISMATCH"
    )


def test_duplicate_origins_cannot_inflate_issuer_evidence(tmp_path: Path) -> None:
    _, plan = _fixture(tmp_path)
    with pytest.raises(ValueError, match="duplicate replay origin"):
        HistoryReplayPlanV1.model_validate(
            {**plan.model_dump(), "origins": (*plan.origins, *plan.origins)}
        )


def test_calibration_rejects_a_substitute_cohort_before_any_forecast(
    tmp_path: Path,
) -> None:
    app, plan = _fixture(tmp_path)
    with pytest.raises(ValueError, match="fixed SEC cohort digest"):
        run_history_replay(
            app, plan.model_copy(update={"evidence_class": "calibration"})
        )


def test_production_cli_rejects_engineering_and_changed_runtime_before_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, plan = _fixture(tmp_path)
    monkeypatch.setattr(cli, "_ensure_tracked_tree_clean", lambda _: None)
    monkeypatch.setattr(cli, "replay_runtime_pins", lambda: {"commit_sha": "b" * 40})
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(canonical_bytes(plan))
    assert cli.main(["--plan", str(plan_path)]) == 1
    assert "requires the fixed calibration cohort" in capsys.readouterr().err
    plan_path.write_bytes(
        canonical_bytes(plan.model_copy(update={"evidence_class": "calibration"}))
    )
    assert cli.main(["--plan", str(plan_path)]) == 1
    assert "exact commit and runtime pins" in capsys.readouterr().err


def test_production_cli_serializes_decimal_statistics_canonically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, plan = _fixture(tmp_path)
    plan = plan.model_copy(update={"evidence_class": "calibration"})
    monkeypatch.setattr(cli, "_ensure_tracked_tree_clean", lambda _: None)
    monkeypatch.setattr(cli, "replay_runtime_pins", lambda: plan.runtime)
    cohort_root = tmp_path / "frozen-evidence"
    monkeypatch.setattr(
        cli,
        "validate_fixed_cohort",
        lambda _, **kwargs: kwargs["cohort_root"] == cohort_root
        or pytest.fail("CLI lost the explicit evidence root"),
    )

    async def execute(_plan, _output, evidence_root):
        assert evidence_root == cohort_root
        return {"statistic": Decimal("12.50"), "runtime": plan.runtime}

    monkeypatch.setattr(cli, "_execute", execute)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(canonical_bytes(plan))
    assert cli.main(["--plan", str(plan_path), "--cohort-root", str(cohort_root)]) == 0
    assert json.loads(capsys.readouterr().out)["statistic"] == "12.50"


@pytest.mark.parametrize(
    "mapping_mode,code",
    [
        ("tampered", "DATA_RELEASE_MAPPING_MISMATCH"),
        ("unbound", "DATA_RELEASE_MAPPING_FACT_MISMATCH"),
        ("missing", "MAPPING_NOT_FOUND"),
    ],
)
def test_composer_rejects_unbound_or_changed_release_mappings(
    tmp_path: Path,
    mapping_mode: str,
    code: str,
) -> None:
    app, plan = _fixture(tmp_path, mapping_mode=mapping_mode)
    row = _rows(run_history_replay(app, plan), "forecast")[0]
    assert row["status"] == "abstain" and row["targets"] == {}
    assert json.loads(canonical_bytes(row))["service_failure"]["code"] == code


def test_label_rejects_fact_mappings_that_were_never_reviewed(tmp_path: Path) -> None:
    app, plan = _fixture(tmp_path, mapping_mode="label-unbound")
    result = run_history_replay(app, plan)
    assert _rows(result, "forecast")[0]["status"] == "provisional"
    label = _rows(result, "label")[0]
    assert label["status"] == "incomplete" and label["targets"] == {}
    assert label["issue_codes"] == ("DATA_RELEASE_MAPPING_FACT_MISMATCH",)


def test_label_requires_the_fixed_mapping_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, plan = _fixture(tmp_path)
    read = FundamentalApplication.read_valuation_evidence
    origin = plan.origins[0]
    assert origin.label_release is not None
    label_id = origin.label_release.snapshot_id

    def wrong_label_version(self, request):
        evidence = read(self, request)
        return (
            evidence.model_copy(
                update={"mapping_version": "different-reviewed-version"}
            )
            if request.snapshot_id == label_id
            else evidence
        )

    monkeypatch.setattr(
        FundamentalApplication, "read_valuation_evidence", wrong_label_version
    )
    result = run_history_replay(app, plan)
    assert _rows(result, "forecast")[0]["status"] == "provisional"
    label = _rows(result, "label")[0]
    assert label["status"] == "incomplete" and label["targets"] == {}
    assert label["issue_codes"] == ("REPLAY_MAPPING_PIN_MISMATCH",)


def test_service_failures_are_stable_and_unexpected_errors_abort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app, plan = _fixture(tmp_path)

    def unavailable(self, request):
        raise ServiceError(
            "fixture_source_unavailable",
            "transient description",
            status_code=503,
            retryable=True,
        )

    monkeypatch.setattr(FundamentalApplication, "prepare_valuation", unavailable)
    first = run_history_replay(app, plan)
    second = run_history_replay(app, plan)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert (
        json.loads(canonical_bytes(_rows(first, "forecast")[0]))["service_failure"][
            "code"
        ]
        == "fixture_source_unavailable"
    )

    def bug(self, request):
        raise RuntimeError("programming defect")

    monkeypatch.setattr(FundamentalApplication, "prepare_valuation", bug)
    with pytest.raises(RuntimeError, match="programming defect"):
        run_history_replay(app, plan)


def test_preparation_refusal_does_not_become_zero_years(tmp_path: Path) -> None:
    app, plan = _fixture(tmp_path, missing_forecast_field="revenue")
    result = run_history_replay(app, plan)
    forecast = _rows(result, "forecast")[0]
    assert forecast["status"] == "abstain"
    assert forecast["complete_history_years"] is None
    assert forecast["preparation"].historical_metrics.metrics == ()
    assert forecast["preparation"].missing_evidence
    strata = result["report"]["models"]["fcff_dcf"]["history_length_comparison"][
        "strata"
    ]
    assert strata[0]["selected_origins"] == 0
    assert strata[-1]["selected_origins"] == 1
    assert strata[-1]["forecast_issue_counts"]


def _statistical_rows(
    issuer: str,
    years: int | None,
    error: Decimal | None,
    *,
    complete_label: bool = True,
) -> tuple[dict[str, object], dict[str, object]]:
    """Synthetic reductions only; these rows are never release evidence."""
    return (
        {
            "issuer_id": issuer,
            "complete_history_years": years,
            "status": "provisional" if error is not None else "abstain",
            "targets": {"revenue": Decimal(100) + error, "fcff": Decimal(10) + error}
            if error is not None
            else {},
            "issue_codes": () if error is not None else ("MISSING_RELEASE",),
        },
        {
            "issuer_id": issuer,
            "status": "complete" if complete_label else "incomplete",
            "targets": {"revenue": Decimal(100), "fcff": Decimal(10)}
            if complete_label
            else {"revenue": Decimal(100)},
            "issue_codes": () if complete_label else ("MISSING_FCFF_LABEL",),
        },
    )


def test_history_comparison_keeps_unknown_zero_and_unpaired_denominators() -> None:
    rows = [
        _statistical_rows("A", 3, Decimal(10)),
        _statistical_rows("A", 3, Decimal(30)),
        _statistical_rows("B", 5, Decimal(-5)),
        _statistical_rows("C", 0, None),
        _statistical_rows("D", None, None),
        _statistical_rows("E", 4, Decimal(50), complete_label=False),
    ]
    summary = _summary(
        [f for f, _ in rows],
        [label for _, label in rows],
        model_id="fcff_dcf",
        evidence_class="calibration",
    )
    assert summary["paired_complete_origins"] == 3
    assert summary["paired_complete_independent_issuers"] == 2
    assert summary["execution_status"] == "partial"
    assert summary["empirical_status"] == "empirical_underpowered"
    strata = summary["history_length_comparison"]["strata"]
    assert sum(row["selected_origins"] for row in strata) == 6
    assert strata[0]["selected_origins"] == strata[-1]["selected_origins"] == 1
    assert strata[-1]["forecast_issue_counts"] == {"MISSING_RELEASE": 1}
    three = strata[3]["targets"]["fcff"]
    assert three["paired_origins"] == 2
    assert three["independent_issuer_count"] == 1
    assert three["mean_error"] == three["mean_absolute_error"] == Decimal(20)
    assert three["issuer_mean_absolute_error_standard_error"] is None
    assert strata[5]["targets"]["fcff"]["mean_error"] == Decimal(-5)
    assert strata[4]["targets"]["revenue"]["paired_origins"] == 1
    assert strata[4]["targets"]["fcff"]["paired_origins"] == 0
    assert summary["supported_history_threshold"] is None


@pytest.mark.parametrize(
    ("count", "same_issuer", "evidence_class", "expected"),
    [
        (0, False, "calibration", "engineering_blocked"),
        (99, False, "calibration", "empirical_underpowered"),
        (100, True, "calibration", "empirical_underpowered"),
        (100, False, "calibration", "measured_review_required"),
        (100, False, "engineering", "engineering_only"),
    ],
)
def test_empirical_floor_counts_independent_complete_pairs_without_promotion(
    count: int,
    same_issuer: bool,
    evidence_class: Literal["calibration", "engineering"],
    expected: str,
) -> None:
    rows = [
        _statistical_rows("A" if same_issuer else str(i), 5, Decimal(0))
        for i in range(count)
    ] or [_statistical_rows("missing", None, None)]
    summary = _summary(
        [f for f, _ in rows],
        [label for _, label in rows],
        model_id="transition_fcff_dcf",
        evidence_class=evidence_class,
    )
    assert summary["threshold_decision"] == expected
    assert summary["supported_history_threshold"] is None
    assert summary["promotion_missing_evidence"]
    assert not summary["history_length_comparison"][
        "minimum_is_sufficient_for_promotion"
    ]


def test_forecasts_without_complete_labels_are_unmeasured() -> None:
    forecast, label = _statistical_rows("A", 3, Decimal(10), complete_label=False)
    summary = _summary(
        [forecast], [label], model_id="fcff_dcf", evidence_class="calibration"
    )
    assert summary["execution_status"] == "partial"
    assert summary["empirical_status"] == "not_measured"
    assert summary["threshold_decision"] == "unmeasured_no_complete_pairs"


@pytest.mark.parametrize("years", [-1, 6, True, "3"])
def test_out_of_contract_history_cannot_disappear_from_strata(years: object) -> None:
    forecast, label = _statistical_rows("A", 3, Decimal(0))
    forecast["complete_history_years"] = years
    with pytest.raises(ValueError, match="history length"):
        _summary([forecast], [label], model_id="fcff_dcf", evidence_class="engineering")


def test_analytical_protocol_cannot_relax_sample_floor_or_claim_promotion() -> None:
    from pydantic import ValidationError

    for payload in (
        {"minimum_independent_issuers": 1},
        {"promotion_policy_digest": "a" * 64},
    ):
        with pytest.raises(ValidationError):
            HistoryEvidenceProtocolV1.model_validate(payload)
    assert HistoryEvidenceProtocolV1().minimum_independent_issuers == 100
