from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/plan_history_study_precision.py"
PROPOSAL = ROOT / "docs/research/issue-377-protocol-proposal-v3.json"
spec = importlib.util.spec_from_file_location("study_precision", SCRIPT)
assert spec and spec.loader
study = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = study
spec.loader.exec_module(study)


def test_planning_grid_uses_familywise_critical_value_without_promoting() -> None:
    result = study.plan_precision(
        study.decode_design(json.loads(PROPOSAL.read_bytes()))
    )
    # Check the quantile by the independent normal CDF, not inv_cdf again.
    z = float(result["normal_critical_value"])
    assert (1 + math.erf(z / math.sqrt(2))) / 2 == pytest.approx(1 - 0.05 / 64)
    rows = result["scenarios"]
    assert [row["required_pairs_normal_approximation"] for row in rows] == [
        17,
        101,
        401,
        1604,
        6415,
    ]
    assert [row["precision_pairs_normal_approximation"] for row in rows] == [
        11,
        63,
        251,
        1001,
        4002,
    ]
    assert result["legacy_gate_feasible"] is False
    assert result["legacy_gate_changed"] is False
    assert result["empirical_power_or_precision_measured"] is False
    assert result["protocol_approved"] is False
    assert result["promotion_enabled"] is False
    assert result["supported_history_threshold"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("promotion_enabled", True),
        ("promotion_enabled", 0),
        ("supported_history_threshold", 3),
        ("selected_issuers", 90),
        ("selected_issuers", 100.0),
        ("maximum_eligible_label_pairs", 100),
        ("legacy_minimum_complete_pairs", 90),
        ("history_years", [3, 5]),
        ("fixed_manifest_digest", "0" * 64),
    ],
)
def test_population_and_promotion_cannot_change(field: str, value: object) -> None:
    proposal = json.loads(PROPOSAL.read_bytes())
    proposal[field] = value
    with pytest.raises(study.DesignError):
        study.decode_design(proposal)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ci_half_width_mase", "0"),
        ("ci_half_width_mase", "NaN"),
        ("detectable_difference_mase", "-1"),
        ("detectable_difference_mase", "Infinity"),
        ("power", "1"),
        ("familywise_alpha", "0.5"),
        ("family_hypotheses", 20),
        ("sd_scenarios_mase", ["0.1", "0.1"]),
        ("sd_scenarios_mase", ["1", "0.1"]),
        ("sd_scenarios_mase", []),
        ("selected_planning_sd", "0.1"),
    ],
)
def test_invalid_or_unapproved_planning_values_fail(field: str, value: object) -> None:
    proposal = json.loads(PROPOSAL.read_bytes())
    proposal["planning"][field] = value
    with pytest.raises(study.DesignError):
        study.decode_design(proposal)


def test_atomic_report_reuses_original_bytes_and_refuses_corruption(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    report = {"output": {"supported_history_threshold": None}}
    first = study.publish_report(output, report)
    path = output / f"{first['report_digest']}.json"
    before = path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns
    assert study.publish_report(output, report)["wrote"] is False
    assert before == (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
    path.write_bytes(b"corrupt")
    with pytest.raises(study.DesignError, match="corrupt"):
        study.publish_report(output, report)
    assert path.read_bytes() == b"corrupt"


def test_interrupted_write_leaves_no_half_report_and_retry_converges(
    tmp_path: Path,
) -> None:
    report = {"value": "immutable"}
    with patch.object(study.os, "replace", side_effect=OSError("interrupted")):
        with pytest.raises(OSError, match="interrupted"):
            study.publish_report(tmp_path, report)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".publication.lock"]
    assert study.publish_report(tmp_path, report)["wrote"] is True
    assert study.publish_report(tmp_path, report)["wrote"] is False


def test_reports_cannot_be_written_inside_repo_or_through_symlink(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    link = tmp_path / "link"
    link.symlink_to(repository, target_is_directory=True)
    for path in (repository, repository / "reports", link / "reports"):
        with pytest.raises(study.DesignError, match="outside"):
            study.publish_report(path, {}, repository)
    assert not list(repository.iterdir())
    other_checkout = tmp_path / "another-checkout"
    other_checkout.mkdir()
    (other_checkout / ".git").write_text("gitdir: /separate/git/metadata")
    with pytest.raises(study.DesignError, match="outside"):
        study.publish_report(other_checkout / "reports", {}, repository)


def test_fresh_process_repeat_and_concurrent_publication(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "scripts").mkdir(parents=True)
    script = repository / "scripts" / SCRIPT.name
    proposal = repository / PROPOSAL.name
    shutil.copyfile(SCRIPT, script)
    shutil.copyfile(PROPOSAL, proposal)
    for args in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Study Test",
            "-c",
            "user.email=study@example.invalid",
            "commit",
            "-qm",
            "test input",
        ],
    ):
        subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    output = tmp_path / "reports"
    command = [
        sys.executable,
        "-B",
        str(script),
        "--proposal",
        str(proposal),
        "--exact-commit",
        head,
        "--output-directory",
        str(output),
    ]
    processes = [
        subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))
    assert sorted(result["wrote"] for result in results) == [False, True]
    assert results[0]["report_digest"] == results[1]["report_digest"]
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}
    repeated = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(repeated.stdout)["wrote"] is False
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    }
    proposal.write_bytes(b"{}")
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode == 2
    assert "exact clean" in refused.stderr
