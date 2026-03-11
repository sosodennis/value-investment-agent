from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

REQUIRED_THRESHOLD_KEYS: tuple[str, ...] = (
    "max_extreme_upside_rate",
    "min_guardrail_hit_rate",
    "min_reinvestment_guardrail_hit_rate",
    "max_shares_scope_mismatch_rate",
    "max_consensus_gap_median_abs",
    "max_consensus_gap_p90_abs",
    "min_consensus_gap_count",
    "max_consensus_degraded_rate",
    "min_consensus_confidence_weight",
    "min_consensus_quality_count",
    "max_consensus_provider_blocked_rate",
    "max_consensus_parse_missing_rate",
    "min_consensus_warning_code_count",
    "min_replay_trace_contract_pass_rate",
    "max_replay_intrinsic_delta_p90_abs",
    "max_replay_quality_block_rate",
    "min_replay_cache_hit_rate",
    "max_replay_warm_latency_p90_ms",
    "max_replay_cold_latency_p90_ms",
    "max_replay_arelle_parse_latency_p90_ms",
    "max_replay_arelle_runtime_lock_wait_p90_ms",
    "max_replay_validation_rule_drift_count",
)

INT_THRESHOLD_KEYS: tuple[str, ...] = (
    "min_consensus_gap_count",
    "min_consensus_quality_count",
    "min_consensus_warning_code_count",
    "max_replay_validation_rule_drift_count",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate fundamental gate profiles config.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Gate profiles config JSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.path)
    issues = _validate_payload(payload)
    output = {
        "path": str(args.path),
        "gate_passed": len(issues) == 0,
        "issues": issues,
    }
    print(json.dumps(output, ensure_ascii=False))
    if issues:
        return 1
    return 0


def _read_payload(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("config root must be an object")
    return parsed


def _validate_payload(payload: Mapping[str, object]) -> list[str]:
    issues: list[str] = []

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        issues.append("schema_version_missing_or_invalid")

    default_profile = payload.get("default_profile")
    if not isinstance(default_profile, str) or not default_profile:
        issues.append("default_profile_missing_or_invalid")

    profiles_raw = payload.get("profiles")
    if not isinstance(profiles_raw, Mapping):
        issues.append("profiles_missing_or_invalid")
        return issues

    if not profiles_raw:
        issues.append("profiles_empty")
        return issues

    if isinstance(default_profile, str) and default_profile:
        if default_profile not in profiles_raw:
            issues.append("default_profile_not_found")

    for profile_name, profile_payload in profiles_raw.items():
        if not isinstance(profile_name, str) or not profile_name:
            issues.append("profile_name_invalid")
            continue
        if not isinstance(profile_payload, Mapping):
            issues.append(f"profile_invalid:{profile_name}")
            continue
        issues.extend(
            _validate_profile(profile_name=profile_name, payload=profile_payload)
        )
    return issues


def _validate_profile(*, profile_name: str, payload: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append(f"profile_description_missing_or_invalid:{profile_name}")

    thresholds_raw = payload.get("thresholds")
    if not isinstance(thresholds_raw, Mapping):
        issues.append(f"profile_thresholds_missing_or_invalid:{profile_name}")
        return issues

    for key in REQUIRED_THRESHOLD_KEYS:
        raw = thresholds_raw.get(key)
        if raw is None:
            issues.append(f"profile_threshold_missing:{profile_name}.{key}")
            continue
        if key in INT_THRESHOLD_KEYS:
            if not _is_int_like(raw):
                issues.append(f"profile_threshold_invalid_type:{profile_name}.{key}")
        else:
            if not _is_float_like(raw):
                issues.append(f"profile_threshold_invalid_type:{profile_name}.{key}")
    return issues


def _is_int_like(raw: object) -> bool:
    if isinstance(raw, bool):
        return False
    if isinstance(raw, int):
        return True
    if isinstance(raw, float):
        return raw == int(raw)
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            return False
        try:
            parsed = float(token)
        except ValueError:
            return False
        return parsed == int(parsed)
    return False


def _is_float_like(raw: object) -> bool:
    if isinstance(raw, bool):
        return False
    if isinstance(raw, int | float):
        return True
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            return False
        try:
            float(token)
        except ValueError:
            return False
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
