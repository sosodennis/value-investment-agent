from __future__ import annotations

import json
from pathlib import Path

from src.agents.fundamental.domain.valuation.calibration.fitting_service import (
    fit_forward_signal_calibration_config,
)
from src.agents.fundamental.domain.valuation.calibration.io_service import (
    load_forward_signal_calibration_observations,
)
from src.agents.fundamental.domain.valuation.policies.forward_signal_calibration_service import (
    DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG,
)


def test_fit_forward_signal_calibration_config_falls_back_when_samples_insufficient(
    tmp_path: Path,
) -> None:
    observations = [
        {
            "metric": "growth_outlook",
            "source_type": "mda",
            "raw_basis_points": 100.0,
            "target_basis_points": 70.0,
        },
        {
            "metric": "margin_outlook",
            "source_type": "xbrl_auto",
            "raw_basis_points": -150.0,
            "target_basis_points": -90.0,
        },
    ]
    path = _write_jsonl_rows(tmp_path, observations)
    load_result = load_forward_signal_calibration_observations(path)

    fit_result = fit_forward_signal_calibration_config(
        load_result.observations,
        mapping_version="test_v1",
        min_samples=10,
    )

    assert fit_result.report.used_fallback is True
    assert fit_result.report.fallback_reason == "insufficient_samples"
    assert (
        fit_result.config.mapping_bins
        == DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG.mapping_bins
    )


def test_fit_forward_signal_calibration_config_produces_monotonic_bins(
    tmp_path: Path,
) -> None:
    observations = []
    for raw in range(50, 321, 10):
        observations.append(
            {
                "metric": "growth_outlook",
                "source_type": "mda",
                "raw_basis_points": float(raw),
                "target_basis_points": float(raw * 0.7),
            }
        )

    path = _write_jsonl_rows(tmp_path, observations)
    load_result = load_forward_signal_calibration_observations(path)
    fit_result = fit_forward_signal_calibration_config(
        load_result.observations,
        mapping_version="test_v2",
        min_samples=10,
    )

    assert fit_result.report.used_fallback is False
    slopes = [slope for _, slope in fit_result.config.mapping_bins]
    assert all(slope > 0 for slope in slopes)
    assert all(slopes[index] <= slopes[index - 1] for index in range(1, len(slopes)))
    assert fit_result.config.mapping_version == "test_v2"


def test_load_forward_signal_calibration_observations_supports_json_array(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forward_signal_calibration_obs_array.json"
    payload = [
        {
            "metric": "growth_outlook",
            "source_type": "mda",
            "raw_basis_points": 120.0,
            "target_basis_points": 80.0,
        },
        {
            "metric": "",
            "source_type": "mda",
            "raw_basis_points": 120.0,
            "target_basis_points": 80.0,
        },
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    load_result = load_forward_signal_calibration_observations(path)

    assert len(load_result.observations) == 1
    assert load_result.dropped_rows == 1


def _write_jsonl_rows(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "forward_signal_calibration_obs.jsonl"
    path.write_text(
        "\n".join(json.dumps(item) for item in rows) + "\n",
        encoding="utf-8",
    )
    return path
