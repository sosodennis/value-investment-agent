from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "config" / "fundamental_gate_profiles.json"

ENV_KEY_MAP: dict[str, str] = {
    "max_extreme_upside_rate": "FUNDAMENTAL_MAX_EXTREME_UPSIDE_RATE",
    "min_guardrail_hit_rate": "FUNDAMENTAL_MIN_GUARDRAIL_HIT_RATE",
    "min_reinvestment_guardrail_hit_rate": (
        "FUNDAMENTAL_MIN_REINVESTMENT_GUARDRAIL_HIT_RATE"
    ),
    "max_shares_scope_mismatch_rate": "FUNDAMENTAL_MAX_SHARES_SCOPE_MISMATCH_RATE",
    "max_consensus_gap_median_abs": "FUNDAMENTAL_MAX_CONSENSUS_GAP_MEDIAN_ABS",
    "max_consensus_gap_p90_abs": "FUNDAMENTAL_MAX_CONSENSUS_GAP_P90_ABS",
    "min_consensus_gap_count": "FUNDAMENTAL_MIN_CONSENSUS_GAP_COUNT",
    "max_consensus_degraded_rate": "FUNDAMENTAL_MAX_CONSENSUS_DEGRADED_RATE",
    "min_consensus_confidence_weight": ("FUNDAMENTAL_MIN_CONSENSUS_CONFIDENCE_WEIGHT"),
    "min_consensus_quality_count": "FUNDAMENTAL_MIN_CONSENSUS_QUALITY_COUNT",
    "max_consensus_provider_blocked_rate": (
        "FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE"
    ),
    "max_consensus_parse_missing_rate": "FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE",
    "min_consensus_warning_code_count": "FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT",
    "min_replay_trace_contract_pass_rate": (
        "FUNDAMENTAL_MIN_REPLAY_TRACE_CONTRACT_PASS_RATE"
    ),
    "max_replay_intrinsic_delta_p90_abs": (
        "FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS"
    ),
    "max_replay_quality_block_rate": "FUNDAMENTAL_MAX_REPLAY_QUALITY_BLOCK_RATE",
    "min_replay_cache_hit_rate": "FUNDAMENTAL_MIN_REPLAY_CACHE_HIT_RATE",
    "max_replay_warm_latency_p90_ms": ("FUNDAMENTAL_MAX_REPLAY_WARM_LATENCY_P90_MS"),
    "max_replay_cold_latency_p90_ms": ("FUNDAMENTAL_MAX_REPLAY_COLD_LATENCY_P90_MS"),
    "max_replay_arelle_parse_latency_p90_ms": (
        "FUNDAMENTAL_MAX_REPLAY_ARELLE_PARSE_LATENCY_P90_MS"
    ),
    "max_replay_arelle_runtime_lock_wait_p90_ms": (
        "FUNDAMENTAL_MAX_REPLAY_ARELLE_RUNTIME_LOCK_WAIT_P90_MS"
    ),
    "max_replay_validation_rule_drift_count": (
        "FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT"
    ),
}

INT_THRESHOLD_KEYS = {
    "min_consensus_gap_count",
    "min_consensus_quality_count",
    "min_consensus_warning_code_count",
    "max_replay_validation_rule_drift_count",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a fundamental gate profile into environment variable pairs."
        )
    )
    parser.add_argument(
        "--profile",
        type=str,
        required=True,
        help="Profile identifier in gate profile config.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help="Gate profile config JSON path.",
    )
    parser.add_argument(
        "--format",
        choices=("env", "json"),
        default="env",
        help="Output format. 'env' emits KEY=VALUE lines.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.path)
    env_values = _resolve_profile_env_values(payload=payload, profile=args.profile)
    if args.format == "json":
        print(json.dumps(env_values, ensure_ascii=False, sort_keys=True))
    else:
        for key in sorted(env_values.keys()):
            print(f"{key}={env_values[key]}")
    return 0


def _read_payload(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("gate profile config root must be an object")
    return parsed


def _resolve_profile_env_values(
    *,
    payload: Mapping[str, object],
    profile: str,
) -> dict[str, str]:
    profiles_raw = payload.get("profiles")
    if not isinstance(profiles_raw, Mapping):
        raise TypeError("profiles must be an object")

    profile_raw = profiles_raw.get(profile)
    if not isinstance(profile_raw, Mapping):
        raise KeyError(f"profile not found: {profile}")

    thresholds_raw = profile_raw.get("thresholds")
    if not isinstance(thresholds_raw, Mapping):
        raise TypeError(f"profile thresholds missing or invalid: {profile}")

    output: dict[str, str] = {"FUNDAMENTAL_GATE_PROFILE": profile}
    for threshold_key, env_key in ENV_KEY_MAP.items():
        raw = thresholds_raw.get(threshold_key)
        if raw is None:
            raise KeyError(f"profile threshold missing: {profile}.{threshold_key}")
        output[env_key] = _coerce_threshold_value(
            threshold_key=threshold_key,
            raw=raw,
        )
    return output


def _coerce_threshold_value(*, threshold_key: str, raw: object) -> str:
    if threshold_key in INT_THRESHOLD_KEYS:
        if isinstance(raw, bool):
            raise TypeError(f"threshold must be numeric: {threshold_key}")
        if isinstance(raw, int):
            return str(raw)
        if isinstance(raw, float):
            return str(int(raw))
        if isinstance(raw, str):
            normalized = raw.strip()
            if not normalized:
                raise TypeError(f"threshold must be numeric: {threshold_key}")
            return str(int(float(normalized)))
        raise TypeError(f"threshold must be numeric: {threshold_key}")

    if isinstance(raw, bool):
        raise TypeError(f"threshold must be numeric: {threshold_key}")
    if isinstance(raw, int | float):
        return str(float(raw))
    if isinstance(raw, str):
        normalized = raw.strip()
        if not normalized:
            raise TypeError(f"threshold must be numeric: {threshold_key}")
        return str(float(normalized))
    raise TypeError(f"threshold must be numeric: {threshold_key}")


if __name__ == "__main__":
    raise SystemExit(main())
