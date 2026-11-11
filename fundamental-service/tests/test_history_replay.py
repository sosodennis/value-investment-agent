import gzip
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fundamental_service import history_replay
from fundamental_service.history_replay import (
    DEFAULT_EVIDENCE_MANIFEST,
    DEFAULT_MAPPING_REPORT,
    JsonObject,
    ReplayArtifacts,
    ReplayPreflightError,
    build_replay_preflight,
    write_preflight_artifacts,
)
from fundamental_service.serialization import sha256_digest


def _object(value: object) -> JsonObject:
    assert isinstance(value, dict)
    result: JsonObject = {}
    for key, item in value.items():
        assert isinstance(key, str)
        result[key] = item
    return result


def _array(value: object) -> list[object]:
    assert isinstance(value, list)
    result: list[object] = []
    result.extend(value)
    return result


def _artifact_digests(artifacts: ReplayArtifacts) -> dict[str, str]:
    return {name: sha256_digest(value) for name, value in artifacts.items()}


def test_preflight_preserves_fixed_cohort_and_reports_blocked_composer() -> None:
    artifacts = build_replay_preflight()
    report = _object(artifacts["report"])
    forecasts = [
        _object(row) for row in _array(artifacts["forecast_output"]["forecast_rows"])
    ]
    labels = [_object(row) for row in _array(artifacts["label_output"]["issuer_rows"])]
    issuers = _array(artifacts["input"]["issuers"])

    assert report["selected_issuer_count"] == 100
    assert report["supported_history_threshold"] is None
    assert report["status"] == "underpowered"
    assert report["replay_status"] == "preflight_blocked_before_service_composer"
    assert len(issuers) == 100
    assert len(forecasts) == 200
    assert len(labels) == 100
    assert all(row["composer_invoked"] is False for row in forecasts)
    assert all(row["forecast"] is None for row in forecasts)
    assert all(row["valuation_status"] == "not_evaluated" for row in forecasts)
    assert all(row["recommended_disposition"] == "abstain" for row in forecasts)
    assert all(row["eligible_model_label"] is False for row in labels)


def test_preflight_artifact_digests_are_stable_for_the_same_inputs() -> None:
    first = build_replay_preflight()
    second = build_replay_preflight()

    assert _artifact_digests(first) == _artifact_digests(second)


def test_second_artifact_write_reuses_files_without_replacing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = build_replay_preflight()
    first = write_preflight_artifacts(artifacts, tmp_path)
    first_paths = {name: Path(result["path"]) for name, result in first.items()}
    original_bytes = {name: path.read_bytes() for name, path in first_paths.items()}
    original_payloads = {
        name: gzip.decompress(content) for name, content in original_bytes.items()
    }

    assert all(
        path.name == f"{first[name]['sha256']}.json.gz"
        for name, path in first_paths.items()
    )
    assert all(
        hashlib.sha256(original_payloads[name]).hexdigest() == first[name]["sha256"]
        for name in first
    )
    assert original_payloads["label_output"] == history_replay.canonical_bytes(
        artifacts["label_output"]
    )
    assert first_paths["label_output"].stat().st_size < 500_000

    def reject_replace(*args: object, **kwargs: object) -> None:
        raise AssertionError("unchanged artifacts must not be replaced")

    monkeypatch.setattr(history_replay.os, "replace", reject_replace)
    second = write_preflight_artifacts(artifacts, tmp_path)

    assert all(result["wrote"] is True for result in first.values())
    assert all(result["wrote"] is False for result in second.values())
    assert {name: result["sha256"] for name, result in first.items()} == {
        name: result["sha256"] for name, result in second.items()
    }
    assert original_bytes == {
        name: Path(second[name]["path"]).read_bytes() for name in second
    }


def test_capture_failure_remains_in_the_fixed_denominator(tmp_path: Path) -> None:
    evidence_manifest = json.loads(DEFAULT_EVIDENCE_MANIFEST.read_text())
    failed_entry = evidence_manifest["issuers"][0]
    failed_cik = failed_entry["cik"]
    failed_entry.update(
        {
            "capture_status": "failed",
            "evidence_path": None,
            "evidence_sha256": None,
            "source_response_sha256": None,
            "failure_code": "CAPTURE_FAILED_TEST",
        }
    )
    mapping_report = json.loads(DEFAULT_MAPPING_REPORT.read_text())
    report_row = next(
        row for row in mapping_report["issuer_rows"] if row["cik"] == failed_cik
    )
    report_row.update(
        {
            "evidence_status": "capture_failed",
            "source_response_sha256": None,
            "candidate_concepts": [],
        }
    )

    manifest_bytes = (
        json.dumps(
            evidence_manifest, sort_keys=True, indent=2, ensure_ascii=True
        ).encode()
        + b"\n"
    )
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    shutil.copytree(DEFAULT_EVIDENCE_MANIFEST.parent / "data", evidence_root / "data")
    evidence_path = evidence_root / "manifest.json"
    evidence_path.write_bytes(manifest_bytes)
    mapping_report["evidence_manifest_sha256"] = hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    report_path = evidence_root / "report.json"
    report_path.write_text(
        json.dumps(mapping_report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    )

    artifacts = build_replay_preflight(
        evidence_manifest_path=evidence_path,
        mapping_report_path=report_path,
    )
    input_row = next(
        row
        for row in (_object(item) for item in _array(artifacts["input"]["issuers"]))
        if row["cik"] == failed_cik
    )
    label_row = next(
        row
        for row in (
            _object(item) for item in _array(artifacts["label_output"]["issuer_rows"])
        )
        if row["cik"] == failed_cik
    )

    assert artifacts["report"]["selected_issuer_count"] == 100
    assert artifacts["report"]["captured_issuer_count"] == 99
    assert input_row["evidence_capture_status"] == "failed"
    assert input_row["evidence_file_sha256"] is None
    assert label_row["label_status"] == "missing_or_no_qualifying_candidate"
    assert (
        len(
            [
                row
                for row in (
                    _object(item)
                    for item in _array(artifacts["forecast_output"]["forecast_rows"])
                )
                if row["cik"] == failed_cik
            ]
        )
        == 2
    )


def test_preflight_rejects_unbound_mapping_report(tmp_path: Path) -> None:
    report = json.loads(DEFAULT_MAPPING_REPORT.read_text())
    report["evidence_manifest_sha256"] = "0" * 64
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))

    try:
        build_replay_preflight(mapping_report_path=report_path)
    except ReplayPreflightError as error:
        assert str(error) == "mapping report is not bound to the evidence manifest"
    else:
        raise AssertionError("unbound mapping evidence must be rejected")
