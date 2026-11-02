from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REINVESTMENT_CLAMP_PROFILE_PATH_ENV = "FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH"
REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION = "fundamental_reinvestment_clamp_profile_v1"
_DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parent
    / "config"
    / "reinvestment_clamp_profile.default.json"
)


@dataclass(frozen=True)
class DCFGrowthReinvestmentClampProfile:
    severe_scope_mismatch_ratio_threshold: float
    severe_mismatch_capex_terminal_lower_min: float
    severe_mismatch_capex_terminal_lower_year1_ratio: float
    severe_mismatch_wc_terminal_lower_min: float
    severe_mismatch_wc_terminal_lower_year1_ratio: float


@dataclass(frozen=True)
class ReinvestmentClampProfile:
    schema_version: str
    profile_version: str
    dcf_growth: DCFGrowthReinvestmentClampProfile


DEFAULT_REINVESTMENT_CLAMP_PROFILE = ReinvestmentClampProfile(
    schema_version=REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION,
    profile_version="embedded_default_v1_2026_03_09",
    dcf_growth=DCFGrowthReinvestmentClampProfile(
        severe_scope_mismatch_ratio_threshold=0.45,
        severe_mismatch_capex_terminal_lower_min=0.14,
        severe_mismatch_capex_terminal_lower_year1_ratio=1.25,
        severe_mismatch_wc_terminal_lower_min=0.025,
        severe_mismatch_wc_terminal_lower_year1_ratio=0.35,
    ),
)


@dataclass(frozen=True)
class ReinvestmentClampProfileLoadResult:
    profile: ReinvestmentClampProfile
    profile_source: str
    profile_path: str | None
    degraded_reason: str | None


def load_reinvestment_clamp_profile() -> ReinvestmentClampProfileLoadResult:
    return _load_reinvestment_clamp_profile_cached(
        os.getenv(REINVESTMENT_CLAMP_PROFILE_PATH_ENV),
    )


def clear_reinvestment_clamp_profile_cache() -> None:
    _load_reinvestment_clamp_profile_cached.cache_clear()


def parse_reinvestment_clamp_profile(
    payload: Mapping[str, object],
) -> ReinvestmentClampProfile:
    schema_version = payload.get("schema_version")
    if schema_version != REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION:
        raise ValueError("schema_version_mismatch")

    profile_version_raw = payload.get("profile_version")
    profile_version = (
        profile_version_raw.strip() if isinstance(profile_version_raw, str) else ""
    )
    if not profile_version:
        raise ValueError("profile_version_missing_or_invalid")

    dcf_growth_raw = payload.get("dcf_growth")
    if not isinstance(dcf_growth_raw, Mapping):
        raise ValueError("dcf_growth_missing_or_invalid")

    dcf_growth = DCFGrowthReinvestmentClampProfile(
        severe_scope_mismatch_ratio_threshold=_read_float(
            dcf_growth_raw,
            "severe_scope_mismatch_ratio_threshold",
            lower=0.0,
            upper=1.0,
            inclusive_lower=False,
        ),
        severe_mismatch_capex_terminal_lower_min=_read_float(
            dcf_growth_raw,
            "severe_mismatch_capex_terminal_lower_min",
            lower=0.0,
            upper=1.0,
            inclusive_lower=False,
        ),
        severe_mismatch_capex_terminal_lower_year1_ratio=_read_float(
            dcf_growth_raw,
            "severe_mismatch_capex_terminal_lower_year1_ratio",
            lower=0.0,
            upper=10.0,
            inclusive_lower=False,
        ),
        severe_mismatch_wc_terminal_lower_min=_read_float(
            dcf_growth_raw,
            "severe_mismatch_wc_terminal_lower_min",
            lower=-1.0,
            upper=1.0,
            inclusive_lower=True,
        ),
        severe_mismatch_wc_terminal_lower_year1_ratio=_read_float(
            dcf_growth_raw,
            "severe_mismatch_wc_terminal_lower_year1_ratio",
            lower=0.0,
            upper=10.0,
            inclusive_lower=False,
        ),
    )

    return ReinvestmentClampProfile(
        schema_version=REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION,
        profile_version=profile_version,
        dcf_growth=dcf_growth,
    )


@lru_cache(maxsize=4)
def _load_reinvestment_clamp_profile_cached(
    profile_path_from_env: str | None,
) -> ReinvestmentClampProfileLoadResult:
    env_path = (
        profile_path_from_env.strip()
        if isinstance(profile_path_from_env, str) and profile_path_from_env.strip()
        else None
    )
    if env_path is not None:
        return _load_from_path(
            Path(env_path),
            profile_source="env_path",
            fallback_reason_prefix="env_reinvestment_clamp_profile_load_failed",
        )
    return _load_from_path(
        _DEFAULT_PROFILE_PATH,
        profile_source="default_artifact",
        fallback_reason_prefix="default_reinvestment_clamp_profile_load_failed",
    )


def _load_from_path(
    path: Path,
    *,
    profile_source: str,
    fallback_reason_prefix: str,
) -> ReinvestmentClampProfileLoadResult:
    try:
        payload = _read_payload(path)
        profile = parse_reinvestment_clamp_profile(payload)
        return ReinvestmentClampProfileLoadResult(
            profile=profile,
            profile_source=profile_source,
            profile_path=str(path),
            degraded_reason=None,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return ReinvestmentClampProfileLoadResult(
            profile=DEFAULT_REINVESTMENT_CLAMP_PROFILE,
            profile_source="embedded_default",
            profile_path=str(path),
            degraded_reason=f"{fallback_reason_prefix}:{exc}",
        )


def _read_payload(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("profile root must be an object")
    return dict(parsed)


def _read_float(
    payload: Mapping[str, object],
    key: str,
    *,
    lower: float,
    upper: float,
    inclusive_lower: bool,
) -> float:
    raw = payload.get(key)
    value = _coerce_float(raw)
    if value is None:
        raise ValueError(f"{key}_missing_or_invalid")
    if inclusive_lower:
        if value < lower:
            raise ValueError(f"{key}_below_lower_bound")
    elif value <= lower:
        raise ValueError(f"{key}_below_or_equal_lower_bound")
    if value > upper:
        raise ValueError(f"{key}_above_upper_bound")
    return value


def _coerce_float(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            return None
        try:
            return float(token)
        except ValueError:
            return None
    return None
