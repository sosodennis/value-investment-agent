from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "history_analysis", ROOT / "scripts/analyze_history_study.py"
)
assert spec and spec.loader
study = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = study
spec.loader.exec_module(study)


@pytest.fixture
def population(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, dict]:
    decisions, cases = [], []
    for i in range(100):
        issuer, origin = f"CIK:{i:010d}", "2016-02-12T16:26:17Z"
        decisions.append(
            {
                "issuer_id": issuer,
                "decision_at": origin,
                "label_accession": "first-original" if i < 91 else None,
                "label_horizon_matches_forecast": i < 90,
            }
        )
        observations = [
            {
                "model": m,
                "target": t,
                "years": y,
                "status": "missing",
                "label_kind": "unavailable",
                "input_policy": "synthetic-test-policy",
                "comparison_key": study.digest(f"{issuer}-{m}-{t}".encode()),
                "signed_error": None,
                "naive_absolute_error": None,
                "scale": None,
                "reasons": ["TEST_EVIDENCE_MISSING"],
                "evidence_digests": [],
            }
            for m in study.MODELS
            for t in study.TARGETS
            for y in study.WINDOWS
        ]
        cases.append(
            {"issuer_id": issuer, "decision_at": origin, "observations": observations}
        )
    manifest = {"issuer_decisions": decisions}
    manifest_digest = study.digest(study.canonical_bytes(manifest))
    monkeypatch.setattr(study, "MANIFEST_DIGEST", manifest_digest)
    panel = {
        "schema_version": "history-study-loss-panel.v1",
        "analysis_scope": "exploratory_method_validation",
        "fixed_manifest_digest": manifest_digest,
        "cases": cases,
    }
    return manifest, panel


def score(
    panel: dict,
    issuer: int,
    *,
    kind: str = "exact_original",
    scale: str | None = "10",
    errors: tuple[str, ...] = ("10", "20", "30"),
) -> None:
    for row in panel["cases"][issuer]["observations"]:
        if row["model"] == "fcff_dcf" and row["target"] == "next_annual_revenue":
            row.update(
                status="scored",
                label_kind=kind,
                signed_error=errors[row["years"] - 3],
                naive_absolute_error="40",
                scale=scale,
                reasons=[],
                evidence_digests=["a" * 64],
            )


def test_declared_losses_are_paired_by_issuer_and_do_not_promote(
    population: tuple[dict, dict],
) -> None:
    manifest, panel = population
    score(panel, 0)
    score(panel, 1, errors=("30", "40", "50"))
    score(panel, 2, kind="conditional_scenario")
    score(panel, 3, scale="0")
    score(panel, 4, scale=None)
    cases = study.decode_panel(panel, manifest)
    # Use a small deterministic count only inside the unit test.
    original = study.paired_intervals
    with patch.object(
        study,
        "paired_intervals",
        side_effect=lambda vectors, seed: original(vectors, seed, 100),
    ):
        result = study.analyze(cases, "b" * 64, "c" * 64)
    group = result["groups"][0]
    assert group["common_issuer_ids"] == ["CIK:0000000000", "CIK:0000000001"]
    assert [float(h["mean"]) for h in group["hypotheses"]] == [
        2,
        3,
        4,
        -2,
        -1,
        0,
        -2,
        -1,
    ]
    assert group["hypotheses"][0]["all_selected_lower"] == "0.04"
    assert group["hypotheses"][0]["all_selected_upper"] is None
    assert group["hypotheses"][6]["all_selected_lower"] is None
    arm = group["arms"][0]
    assert arm["all_selected_denominator"] == 100
    assert arm["declared_exact_raw"]["independent_issuers"] == 4
    assert arm["scaled_loss_issuers"] == 2
    assert arm["conditional_label_cells_excluded"] == 1
    assert arm["zero_scale_issuers"] == arm["missing_scale_issuers"] == 1
    assert result["retained_cases"][3]["cells"][0]["reasons"] == ["ZERO_TRAINING_SCALE"]
    assert result["retained_cases"][4]["cells"][0]["reasons"] == [
        "MISSING_TRAINING_SCALE"
    ]
    assert len(result["retained_cases"]) == 100
    assert result["supported_history_threshold"] is None
    assert not result["promotion_enabled"]
    assert not result["protocol_review_approved"]
    assert result["sample_status"].startswith("UNDERPOWERED")
    assert sum(len(g["hypotheses"]) for g in result["groups"]) == 32


def test_bootstrap_matches_independent_enumerated_distribution() -> None:
    # All four ordered samples of two issuers: means 1, 2, 2, 3.
    # Contrast stays -1 in every resample; do not present it as certain precision.
    with patch.object(
        study.random.Random, "randrange", side_effect=[0, 0, 0, 1, 1, 0, 1, 1]
    ):
        first, contrast = study.paired_intervals(
            ((1.0, -1.0), (3.0, -1.0)), "a" * 64, 4
        )
    tail = 0.05 / 64
    assert float(first["lower"]) == pytest.approx(1 + 3 * tail)
    assert float(first["upper"]) == pytest.approx(3 - 3 * tail)
    assert float(first["half_width"]) == pytest.approx(1 - 3 * tail)
    assert contrast["status"] == "DEGENERATE_EMPIRICAL_DISTRIBUTION"
    assert contrast["lower"] is contrast["upper"] is None


def test_deterministic_paired_resamples_and_insufficient_units() -> None:
    vectors = ((1.0, 4.0), (3.0, 5.0), (8.0, 9.0))
    assert study.paired_intervals(vectors, "a" * 64, 1000) == study.paired_intervals(
        vectors, "a" * 64, 1000
    )
    assert (
        study.paired_intervals(((1.0,),), "a" * 64)[0]["status"]
        == "INSUFFICIENT_INDEPENDENT_ISSUERS"
    )


def test_full_pinned_replicate_count_retains_pairing() -> None:
    result = study.paired_intervals(((1.0, 4.0), (3.0, 6.0)), "a" * 64)
    # This population has only the three possible means 1, 2, 3 (and 4, 5, 6).
    assert (result[0]["lower"], result[0]["upper"]) == ("1.0", "3.0")
    assert (result[1]["lower"], result[1]["upper"]) == ("4.0", "6.0")


@pytest.mark.parametrize(
    "change",
    [
        "missing_issuer",
        "duplicate_issuer",
        "substitute_origin",
        "extra_scenario_row",
        "missing_arm",
        "reorder_cases",
        "reorder_arms",
        "fake_confirmatory",
        "invented_model",
        "short_window",
        "negative_scale",
        "nan_loss",
        "numeric_loss",
        "negative_naive",
        "scored_missing_label",
        "scored_horizon_mismatch",
        "different_scale",
        "different_baseline",
        "different_comparison_key",
        "different_policy",
        "policy_search",
        "no_failure_reason",
        "no_evidence",
        "bad_digest",
        "unknown_field",
        "numeric_on_abstention",
    ],
)
def test_invalid_population_pairing_and_numeric_contracts_fail(
    population: tuple[dict, dict], change: str
) -> None:
    manifest, panel = population
    score(panel, 0)
    row = panel["cases"][0]["observations"][0]
    if change == "missing_issuer":
        panel["cases"].pop()
    elif change == "duplicate_issuer":
        panel["cases"][-1] = panel["cases"][0]
    elif change == "substitute_origin":
        panel["cases"][0]["decision_at"] = "2017-01-01T00:00:00Z"
    elif change == "extra_scenario_row":
        panel["cases"][0]["observations"].append(dict(row))
    elif change == "missing_arm":
        panel["cases"][0]["observations"].pop()
    elif change == "reorder_cases":
        panel["cases"].reverse()
    elif change == "reorder_arms":
        panel["cases"][0]["observations"].reverse()
    elif change == "fake_confirmatory":
        panel["analysis_scope"] = "approved"
    elif change == "invented_model":
        row["model"] = "unimplemented-v999"
    elif change == "short_window":
        row["years"] = 2
    elif change == "negative_scale":
        row["scale"] = "-1"
    elif change == "nan_loss":
        row["signed_error"] = "NaN"
    elif change == "numeric_loss":
        row["signed_error"] = 1
    elif change == "negative_naive":
        row["naive_absolute_error"] = "-1"
    elif change == "scored_missing_label":
        score(panel, 99)
    elif change == "scored_horizon_mismatch":
        score(panel, 90)
    elif change == "different_scale":
        row["scale"] = "100"
    elif change == "different_baseline":
        row["naive_absolute_error"] = "1"
    elif change == "different_comparison_key":
        row["comparison_key"] = "d" * 64
    elif change == "different_policy":
        row["input_policy"] = "another-policy"
    elif change == "policy_search":
        for r in panel["cases"][1]["observations"]:
            r["input_policy"] = "another-policy"
    elif change == "no_failure_reason":
        panel["cases"][99]["observations"][0]["reasons"] = []
    elif change == "no_evidence":
        row["evidence_digests"] = []
    elif change == "bad_digest":
        row["comparison_key"] = "fake"
    elif change == "unknown_field":
        row["approved"] = True
    elif change == "numeric_on_abstention":
        panel["cases"][99]["observations"][0]["signed_error"] = "0"
    with pytest.raises(study.DesignError):
        study.decode_panel(panel, manifest)


def test_manifest_hash_cannot_be_replaced(population: tuple[dict, dict]) -> None:
    manifest, panel = population
    manifest["extra"] = "changed"
    with pytest.raises(study.DesignError, match="manifest digest"):
        study.decode_panel(panel, manifest)


def test_duplicate_json_fields_cannot_discard_failures(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"cases": ["failed"], "cases": []}')
    with pytest.raises(study.DesignError, match="duplicate JSON"):
        study.read_document(path)


def test_cli_repeats_in_fresh_processes_and_refuses_protocol_relabeling(
    population: tuple[dict, dict], tmp_path: Path
) -> None:
    manifest, panel = population
    repository = tmp_path / "checkout"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    docs = repository / "docs/research"
    docs.mkdir(parents=True)
    for filename in ("analyze_history_study.py", "plan_history_study_precision.py"):
        raw = (ROOT / "scripts" / filename).read_text()
        # Synthetic manifests are allowed only in this disposable test checkout.
        raw = raw.replace(
            "448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a",
            panel["fixed_manifest_digest"],
        )
        (scripts / filename).write_text(raw)
    shutil.copyfile(
        ROOT / "docs/research/issue-377-methods-v4.json",
        docs / "issue-377-methods-v4.json",
    )
    for name, value in (("manifest", manifest), ("panel", panel)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "synthetic",
        ],
    ):
        subprocess.run(command, cwd=repository, check=True, capture_output=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    output = tmp_path / "reports"
    command = [
        sys.executable,
        "-B",
        str(scripts / "analyze_history_study.py"),
        "--protocol",
        str(docs / "issue-377-methods-v4.json"),
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--panel",
        str(tmp_path / "panel.json"),
        "--exact-commit",
        head,
        "--output-directory",
        str(output),
    ]
    first = json.loads(subprocess.check_output(command, cwd=repository))
    before = {
        p.name: (p.read_bytes(), p.stat().st_size, p.stat().st_mtime_ns)
        for p in output.iterdir()
    }
    second = json.loads(subprocess.check_output(command, cwd=repository))
    assert first["wrote"] and not second["wrote"]
    assert {k: v for k, v in first.items() if k != "wrote"} == {
        k: v for k, v in second.items() if k != "wrote"
    }
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_size, p.stat().st_mtime_ns)
        for p in output.iterdir()
    }
    invalid_protocol = tmp_path / "approved.json"
    altered = json.loads((docs / "issue-377-methods-v4.json").read_bytes())
    altered["promotion_enabled"] = True
    invalid_protocol.write_text(json.dumps(altered))
    changed = command.copy()
    changed[changed.index("--protocol") + 1] = str(invalid_protocol)
    refusal = subprocess.run(changed, cwd=repository, capture_output=True, text=True)
    assert refusal.returncode == 2 and "pinned methods" in refusal.stderr
    assert set(before) == {p.name for p in output.iterdir()}
