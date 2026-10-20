from __future__ import annotations

import json
from pathlib import Path

from scripts.run_forward_signal_calibration_pipeline import main


def test_calibration_pipeline_uses_current_market_data_facade(
    monkeypatch, tmp_path: Path
) -> None:
    replay_report = tmp_path / "replay.json"
    replay_report.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "ticker": "EXM",
                        "target_consensus_mean_price": 105.0,
                        "intrinsic_value": 102.0,
                        "current_price": 100.0,
                        "forward_signal_summary": {
                            "raw_growth_adjustment_basis_points": 20.0,
                            "raw_margin_adjustment_basis_points": 10.0,
                            "source_types": ["replay"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    dataset_output = tmp_path / "dataset.jsonl"
    artifact_output = tmp_path / "mapping.json"
    report_output = tmp_path / "pipeline-report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_forward_signal_calibration_pipeline.py",
            "--replay-report",
            str(replay_report),
            "--dataset-output",
            str(dataset_output),
            "--artifact-output",
            str(artifact_output),
            "--mapping-version",
            "test_mapping",
            "--min-samples",
            "1",
            "--no-live-market-data",
            "--report-output",
            str(report_output),
            "--require-fit",
        ],
    )

    assert main() == 0
    assert dataset_output.exists()
    assert artifact_output.exists()
    assert report_output.exists()
