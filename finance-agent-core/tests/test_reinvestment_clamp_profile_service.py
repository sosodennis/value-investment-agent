from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.fundamental.domain.valuation.parameterization.reinvestment_clamp_profile_service import (
    REINVESTMENT_CLAMP_PROFILE_PATH_ENV,
    clear_reinvestment_clamp_profile_cache,
    load_reinvestment_clamp_profile,
)


def test_load_reinvestment_clamp_profile_from_default_artifact() -> None:
    clear_reinvestment_clamp_profile_cache()
    result = load_reinvestment_clamp_profile()
    assert result.degraded_reason is None
    assert result.profile_source == "default_artifact"
    assert result.profile.schema_version == "fundamental_reinvestment_clamp_profile_v1"
    assert result.profile.profile_version == "reinvestment_clamp_profile_v1_2026_03_09"


def test_load_reinvestment_clamp_profile_from_env_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "reinvestment_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_v1",
                "profile_version": "reinvestment_clamp_profile_v1_test",
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.5,
                    "severe_mismatch_capex_terminal_lower_min": 0.16,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.1,
                    "severe_mismatch_wc_terminal_lower_min": 0.03,
                    "severe_mismatch_wc_terminal_lower_year1_ratio": 0.4,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(REINVESTMENT_CLAMP_PROFILE_PATH_ENV, str(profile_path))
    clear_reinvestment_clamp_profile_cache()

    result = load_reinvestment_clamp_profile()
    assert result.degraded_reason is None
    assert result.profile_source == "env_path"
    assert result.profile.profile_version == "reinvestment_clamp_profile_v1_test"
    assert result.profile.dcf_growth.severe_scope_mismatch_ratio_threshold == 0.5


def test_load_reinvestment_clamp_profile_invalid_env_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broken_path = tmp_path / "broken_profile.json"
    broken_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_v1",
                "profile_version": "broken",
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.5,
                    "severe_mismatch_capex_terminal_lower_min": 0.16,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.1,
                    "severe_mismatch_wc_terminal_lower_min": 0.03,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(REINVESTMENT_CLAMP_PROFILE_PATH_ENV, str(broken_path))
    clear_reinvestment_clamp_profile_cache()

    result = load_reinvestment_clamp_profile()
    assert result.profile_source == "embedded_default"
    assert result.degraded_reason is not None
    assert "env_reinvestment_clamp_profile_load_failed" in result.degraded_reason
    assert result.profile.profile_version == "embedded_default_v1_2026_03_09"
