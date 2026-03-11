from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.agents.fundamental.subdomains.forward_signals.domain.policies.forward_signal_calibration_service import (
    DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG,
    ForwardSignalCalibrationConfig,
    parse_forward_signal_calibration_config,
)

FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV = (
    "FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH"
)
_DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parent
    / "config"
    / "forward_signal_calibration.default.json"
)


@dataclass(frozen=True)
class ForwardSignalCalibrationLoadResult:
    config: ForwardSignalCalibrationConfig
    mapping_source: str
    mapping_path: str | None
    degraded_reason: str | None


def load_forward_signal_calibration_mapping() -> ForwardSignalCalibrationLoadResult:
    return _load_forward_signal_calibration_mapping_cached(
        os.getenv(FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV),
    )


def clear_forward_signal_calibration_mapping_cache() -> None:
    _load_forward_signal_calibration_mapping_cached.cache_clear()


@lru_cache(maxsize=4)
def _load_forward_signal_calibration_mapping_cached(
    mapping_path_from_env: str | None,
) -> ForwardSignalCalibrationLoadResult:
    env_path = (
        mapping_path_from_env.strip()
        if isinstance(mapping_path_from_env, str) and mapping_path_from_env.strip()
        else None
    )
    if env_path is not None:
        return _load_from_path(
            Path(env_path),
            mapping_source="env_path",
            fallback_reason_prefix="env_mapping_load_failed",
        )
    return _load_from_path(
        _DEFAULT_MAPPING_PATH,
        mapping_source="default_artifact",
        fallback_reason_prefix="default_mapping_load_failed",
    )


def _load_from_path(
    path: Path,
    *,
    mapping_source: str,
    fallback_reason_prefix: str,
) -> ForwardSignalCalibrationLoadResult:
    try:
        payload = _read_mapping_payload(path)
        config = parse_forward_signal_calibration_config(payload)
        return ForwardSignalCalibrationLoadResult(
            config=config,
            mapping_source=mapping_source,
            mapping_path=str(path),
            degraded_reason=None,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return ForwardSignalCalibrationLoadResult(
            config=DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG,
            mapping_source="embedded_default",
            mapping_path=str(path),
            degraded_reason=f"{fallback_reason_prefix}:{exc}",
        )


def _read_mapping_payload(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("mapping artifact root must be an object")
    return dict(parsed)
