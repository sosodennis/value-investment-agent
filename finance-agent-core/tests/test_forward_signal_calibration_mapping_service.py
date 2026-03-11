from __future__ import annotations

import json

from src.agents.fundamental.core_valuation.domain.parameterization.forward_signal_calibration_mapping_service import (
    FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV,
    clear_forward_signal_calibration_mapping_cache,
    load_forward_signal_calibration_mapping,
)
from src.agents.fundamental.forward_signals.domain.policies.forward_signal_calibration_service import (
    DEFAULT_FORWARD_SIGNAL_CALIBRATION_MAPPING_VERSION,
)


def test_load_forward_signal_calibration_mapping_uses_default_artifact(
    monkeypatch,
) -> None:
    monkeypatch.delenv(FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV, raising=False)
    clear_forward_signal_calibration_mapping_cache()

    result = load_forward_signal_calibration_mapping()

    assert result.mapping_source == "default_artifact"
    assert result.degraded_reason is None
    assert result.mapping_path is not None
    assert (
        result.config.mapping_version
        == DEFAULT_FORWARD_SIGNAL_CALIBRATION_MAPPING_VERSION
    )


def test_load_forward_signal_calibration_mapping_supports_env_override(
    monkeypatch,
    tmp_path,
) -> None:
    artifact_path = tmp_path / "forward_signal_mapping.json"
    artifact_path.write_text(
        json.dumps(
            {
                "mapping_version": "forward_signal_calibration_test_v2",
                "source_multiplier": {"mda": 1.0, "xbrl_auto": 0.9},
                "metric_multiplier": {
                    "growth_outlook": 0.95,
                    "margin_outlook": 0.8,
                },
                "mapping_bins": [[40.0, 1.0], [120.0, 0.7], [300.0, 0.5]],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV,
        str(artifact_path),
    )
    clear_forward_signal_calibration_mapping_cache()

    result = load_forward_signal_calibration_mapping()

    assert result.mapping_source == "env_path"
    assert result.degraded_reason is None
    assert result.mapping_path == str(artifact_path)
    assert result.config.mapping_version == "forward_signal_calibration_test_v2"
    assert result.config.mapping_bins == ((40.0, 1.0), (120.0, 0.7), (300.0, 0.5))


def test_load_forward_signal_calibration_mapping_falls_back_on_invalid_artifact(
    monkeypatch,
    tmp_path,
) -> None:
    artifact_path = tmp_path / "invalid_forward_signal_mapping.json"
    artifact_path.write_text('{"mapping_version":"broken"}', encoding="utf-8")

    monkeypatch.setenv(
        FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV,
        str(artifact_path),
    )
    clear_forward_signal_calibration_mapping_cache()

    result = load_forward_signal_calibration_mapping()

    assert result.mapping_source == "embedded_default"
    assert result.degraded_reason is not None
    assert result.degraded_reason.startswith("env_mapping_load_failed:")
    assert (
        result.config.mapping_version
        == DEFAULT_FORWARD_SIGNAL_CALIBRATION_MAPPING_VERSION
    )
