from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "fundamental_live_replay_cohort_config.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run live replay cohort gate from discovery config "
            "(manifest build -> replay checks -> cohort gate)."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to live replay cohort config JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Output directory for generated artifacts.",
    )
    parser.add_argument(
        "--cycle-tag",
        type=str,
        default=None,
        help="Cycle tag appended to output artifact names.",
    )
    parser.add_argument(
        "--discover-root",
        type=Path,
        default=None,
        help="Optional override for discovery root path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = _load_config(args.config)
    cycle_tag = args.cycle_tag or _default_cycle_tag()

    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    discover_root = _resolve_discover_root(config=config, args=args)
    discover_glob = _coerce_text(config, key="discover_glob")
    discover_recursive = _coerce_bool(config, key="discover_recursive")
    ticker_allowlist = _resolve_ticker_allowlist(config)
    latest_per_ticker = _coerce_bool(config, key="latest_per_ticker")
    min_cases = _coerce_int(config, key="min_cases")
    min_unique_tickers = _coerce_int(config, key="min_unique_tickers")
    min_pass_rate = _coerce_float(config, key="min_pass_rate")
    max_intrinsic_delta_p90_abs = _resolve_optional_gate_float(
        config=config,
        config_key="max_intrinsic_delta_p90_abs",
        env_key="FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS",
    )
    max_quality_block_rate = _resolve_optional_gate_float(
        config=config,
        config_key="max_quality_block_rate",
        env_key="FUNDAMENTAL_MAX_REPLAY_QUALITY_BLOCK_RATE",
    )
    min_cache_hit_rate = _resolve_optional_gate_float(
        config=config,
        config_key="min_cache_hit_rate",
        env_key="FUNDAMENTAL_MIN_REPLAY_CACHE_HIT_RATE",
    )
    max_warm_latency_p90_ms = _resolve_optional_gate_float(
        config=config,
        config_key="max_warm_latency_p90_ms",
        env_key="FUNDAMENTAL_MAX_REPLAY_WARM_LATENCY_P90_MS",
    )
    max_cold_latency_p90_ms = _resolve_optional_gate_float(
        config=config,
        config_key="max_cold_latency_p90_ms",
        env_key="FUNDAMENTAL_MAX_REPLAY_COLD_LATENCY_P90_MS",
    )
    max_arelle_parse_latency_p90_ms = _resolve_optional_gate_float(
        config=config,
        config_key="max_arelle_parse_latency_p90_ms",
        env_key="FUNDAMENTAL_MAX_REPLAY_ARELLE_PARSE_LATENCY_P90_MS",
    )
    max_arelle_runtime_lock_wait_p90_ms = _resolve_optional_gate_float(
        config=config,
        config_key="max_arelle_runtime_lock_wait_p90_ms",
        env_key="FUNDAMENTAL_MAX_REPLAY_ARELLE_RUNTIME_LOCK_WAIT_P90_MS",
    )
    max_validation_rule_drift_count = _resolve_optional_gate_int(
        config=config,
        config_key="max_validation_rule_drift_count",
        env_key="FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT",
    )
    stage_root = _resolve_path(Path(_coerce_text(config, key="stage_root")))
    stage_prefix = _coerce_text(config, key="stage_prefix")
    require_relative = _coerce_bool(config, key="require_relative_input_paths")
    profile = _coerce_text(config, key="profile")
    enable_prewarm = _resolve_prewarm_enabled(config)
    prewarm_default_years = _resolve_prewarm_default_years(config)

    stage_dir = stage_root / f"{stage_prefix}_{cycle_tag}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / f"fundamental_replay_manifest_live_{cycle_tag}.json"
    replay_report_path = (
        output_dir / f"fundamental_replay_checks_report_live_{cycle_tag}.json"
    )
    cohort_gate_path = output_dir / f"fundamental_replay_cohort_gate_{cycle_tag}.json"
    run_path = output_dir / f"fundamental_live_replay_cohort_run_{cycle_tag}.json"

    _run_command(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_fundamental_replay_manifest.py"),
            "--discover-root",
            str(discover_root),
            "--discover-glob",
            discover_glob,
            "--ticker-allowlist",
            ",".join(ticker_allowlist),
            "--stage-dir",
            str(stage_dir),
            "--output",
            str(manifest_path),
        ]
        + (["--discover-recursive"] if discover_recursive else [])
        + (["--latest-per-ticker"] if latest_per_ticker else [])
    )

    prewarm_summary = _run_xbrl_prewarm_from_manifest(
        manifest_path=manifest_path,
        default_years=prewarm_default_years,
        enabled=enable_prewarm,
    )

    _run_command(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_fundamental_replay_checks.py"),
            "--manifest",
            str(manifest_path),
            "--report",
            str(replay_report_path),
        ]
    )

    cohort_gate_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "validate_fundamental_replay_cohort_gate.py"),
        "--manifest",
        str(manifest_path),
        "--report",
        str(replay_report_path),
        "--min-cases",
        str(min_cases),
        "--min-unique-tickers",
        str(min_unique_tickers),
        "--min-pass-rate",
        str(min_pass_rate),
        "--require-input-root",
        str(stage_dir),
    ]
    if require_relative:
        cohort_gate_cmd.append("--require-relative-input-paths")
    if max_intrinsic_delta_p90_abs is not None:
        cohort_gate_cmd.extend(
            [
                "--max-intrinsic-delta-p90-abs",
                str(max_intrinsic_delta_p90_abs),
            ]
        )
    if max_quality_block_rate is not None:
        cohort_gate_cmd.extend(
            [
                "--max-quality-block-rate",
                str(max_quality_block_rate),
            ]
        )
    if min_cache_hit_rate is not None:
        cohort_gate_cmd.extend(
            [
                "--min-cache-hit-rate",
                str(min_cache_hit_rate),
            ]
        )
    if max_warm_latency_p90_ms is not None:
        cohort_gate_cmd.extend(
            [
                "--max-warm-latency-p90-ms",
                str(max_warm_latency_p90_ms),
            ]
        )
    if max_cold_latency_p90_ms is not None:
        cohort_gate_cmd.extend(
            [
                "--max-cold-latency-p90-ms",
                str(max_cold_latency_p90_ms),
            ]
        )
    if max_arelle_parse_latency_p90_ms is not None:
        cohort_gate_cmd.extend(
            [
                "--max-arelle-parse-latency-p90-ms",
                str(max_arelle_parse_latency_p90_ms),
            ]
        )
    if max_arelle_runtime_lock_wait_p90_ms is not None:
        cohort_gate_cmd.extend(
            [
                "--max-arelle-runtime-lock-wait-p90-ms",
                str(max_arelle_runtime_lock_wait_p90_ms),
            ]
        )
    if max_validation_rule_drift_count is not None:
        cohort_gate_cmd.extend(
            [
                "--max-validation-rule-drift-count",
                str(max_validation_rule_drift_count),
            ]
        )
    gate_output = _run_command(cohort_gate_cmd, capture_stdout=True)
    cohort_gate_path.write_text(gate_output + "\n", encoding="utf-8")

    gate_payload = json.loads(gate_output)
    result = {
        "profile": profile,
        "cycle_tag": cycle_tag,
        "discover_root": str(discover_root),
        "discover_glob": discover_glob,
        "stage_dir": str(stage_dir),
        "manifest_path": str(manifest_path),
        "replay_report_path": str(replay_report_path),
        "cohort_gate_path": str(cohort_gate_path),
        "issues": list(gate_payload.get("issues", []))
        if isinstance(gate_payload.get("issues"), list)
        else [],
        "gate_passed": bool(gate_payload.get("gate_passed")),
        "max_intrinsic_delta_p90_abs": max_intrinsic_delta_p90_abs,
        "max_quality_block_rate": max_quality_block_rate,
        "min_cache_hit_rate": min_cache_hit_rate,
        "max_warm_latency_p90_ms": max_warm_latency_p90_ms,
        "max_cold_latency_p90_ms": max_cold_latency_p90_ms,
        "max_arelle_parse_latency_p90_ms": max_arelle_parse_latency_p90_ms,
        "max_arelle_runtime_lock_wait_p90_ms": max_arelle_runtime_lock_wait_p90_ms,
        "max_validation_rule_drift_count": max_validation_rule_drift_count,
        "prewarm": prewarm_summary,
        "run_path": str(run_path),
    }
    run_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if result["gate_passed"]:
        return 0
    return 1


def _run_command(command: list[str], *, capture_stdout: bool = False) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(command)
            + f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if capture_stdout:
        return completed.stdout.strip()
    return ""


def _load_config(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("live replay cohort config root must be an object")
    schema_version = payload.get("schema_version")
    if schema_version != "fundamental_live_replay_cohort_config_v1":
        raise TypeError(
            "unsupported config schema_version: "
            f"{schema_version!r}, expected 'fundamental_live_replay_cohort_config_v1'"
        )
    return payload


def _resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _resolve_discover_root(
    *,
    config: Mapping[str, object],
    args: argparse.Namespace,
) -> Path:
    if args.discover_root is not None:
        return _resolve_path(args.discover_root)
    discover_root_env_key = _optional_text(config, key="discover_root_env_key")
    require_discover_root_env = _optional_bool(
        config,
        key="require_discover_root_env",
        default=False,
    )
    if discover_root_env_key is not None:
        env_override = os.getenv(discover_root_env_key, "").strip()
        if env_override:
            return _resolve_path(Path(env_override))
        if require_discover_root_env:
            raise TypeError(
                "discover root environment variable required but missing: "
                f"{discover_root_env_key}"
            )
    env_override = os.getenv("FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT", "").strip()
    if env_override:
        return _resolve_path(Path(env_override))
    return _resolve_path(Path(_coerce_text(config, key="discover_root")))


def _resolve_ticker_allowlist(config: Mapping[str, object]) -> list[str]:
    env_override = os.getenv("FUNDAMENTAL_LIVE_REPLAY_TICKER_ALLOWLIST", "").strip()
    if env_override:
        return [
            token.strip().upper() for token in env_override.split(",") if token.strip()
        ]
    raw = config.get("ticker_allowlist")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise TypeError("ticker_allowlist must be an array of ticker strings")
    tokens: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise TypeError("ticker_allowlist must be an array of ticker strings")
        token = item.strip().upper()
        if token:
            tokens.append(token)
    if not tokens:
        raise TypeError("ticker_allowlist must be non-empty")
    return tokens


def _coerce_text(payload: Mapping[str, object], *, key: str) -> str:
    raw = payload.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise TypeError(f"{key} must be a non-empty string")
    return raw.strip()


def _coerce_bool(payload: Mapping[str, object], *, key: str) -> bool:
    raw = payload.get(key)
    if not isinstance(raw, bool):
        raise TypeError(f"{key} must be a boolean")
    return raw


def _coerce_int(payload: Mapping[str, object], *, key: str) -> int:
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"{key} must be an integer")
    return raw


def _coerce_float(payload: Mapping[str, object], *, key: str) -> float:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise TypeError(f"{key} must be numeric")
    if isinstance(raw, int | float):
        return float(raw)
    raise TypeError(f"{key} must be numeric")


def _optional_text(payload: Mapping[str, object], *, key: str) -> str | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(f"{key} must be a string")
    token = raw.strip()
    if not token:
        return None
    return token


def _optional_bool(
    payload: Mapping[str, object],
    *,
    key: str,
    default: bool,
) -> bool:
    raw = payload.get(key)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise TypeError(f"{key} must be a boolean")
    return raw


def _resolve_optional_gate_float(
    *,
    config: Mapping[str, object],
    config_key: str,
    env_key: str,
) -> float | None:
    env_raw = os.getenv(env_key, "").strip()
    if env_raw:
        try:
            return float(env_raw)
        except ValueError as exc:
            raise TypeError(f"{env_key} must be numeric") from exc

    config_value = _optional_float(config, key=config_key)
    return config_value


def _resolve_optional_gate_int(
    *,
    config: Mapping[str, object],
    config_key: str,
    env_key: str,
) -> int | None:
    env_raw = os.getenv(env_key, "").strip()
    if env_raw:
        try:
            return int(env_raw)
        except ValueError as exc:
            raise TypeError(f"{env_key} must be integer") from exc

    raw = config.get(config_key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"{config_key} must be integer")
    return raw


def _resolve_prewarm_enabled(config: Mapping[str, object]) -> bool:
    env_raw = os.getenv("FUNDAMENTAL_LIVE_REPLAY_ENABLE_PREWARM", "").strip().lower()
    if env_raw in {"1", "true", "yes", "y", "on"}:
        return True
    if env_raw in {"0", "false", "no", "n", "off"}:
        return False
    return _optional_bool(config, key="enable_prewarm", default=False)


def _resolve_prewarm_default_years(config: Mapping[str, object]) -> int:
    env_raw = os.getenv("FUNDAMENTAL_LIVE_REPLAY_PREWARM_DEFAULT_YEARS", "").strip()
    if env_raw:
        try:
            parsed = int(env_raw)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    raw = config.get("prewarm_default_years")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return 5


def _run_xbrl_prewarm_from_manifest(
    *,
    manifest_path: Path,
    default_years: int,
    enabled: bool,
    fetch_payload_fn: Callable[[str, int], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "enabled": enabled,
        "requested_tickers": 0,
        "succeeded_tickers": 0,
        "failed_tickers": 0,
        "errors": [],
        "cache_hit_after_prewarm_rate": None,
    }
    if not enabled:
        return summary

    requests = _build_prewarm_requests_from_manifest(
        manifest_path=manifest_path,
        default_years=default_years,
    )
    summary["requested_tickers"] = len(requests)
    if not requests:
        return summary

    fetch_fn = fetch_payload_fn or _resolve_prewarm_fetch_payload_fn()
    if fetch_fn is None:
        summary["failed_tickers"] = len(requests)
        summary["errors"] = ["prewarm_fetch_fn_unavailable"]
        return summary

    cache_hit_true = 0
    for ticker, years in requests.items():
        try:
            payload = fetch_fn(ticker, years)
        except Exception as exc:
            summary["failed_tickers"] = int(summary["failed_tickers"]) + 1
            errors = summary.get("errors")
            if isinstance(errors, list):
                errors.append(f"{ticker}:{type(exc).__name__}")
            continue

        summary["succeeded_tickers"] = int(summary["succeeded_tickers"]) + 1
        diagnostics_raw = (
            payload.get("diagnostics") if isinstance(payload, Mapping) else None
        )
        if not isinstance(diagnostics_raw, Mapping):
            continue
        cache_raw = diagnostics_raw.get("cache")
        if not isinstance(cache_raw, Mapping):
            continue
        cache_hit = cache_raw.get("cache_hit")
        if isinstance(cache_hit, bool) and cache_hit:
            cache_hit_true += 1

    succeeded = int(summary["succeeded_tickers"])
    if succeeded > 0:
        summary["cache_hit_after_prewarm_rate"] = round(cache_hit_true / succeeded, 6)
    return summary


def _build_prewarm_requests_from_manifest(
    *,
    manifest_path: Path,
    default_years: int,
) -> dict[str, int]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        return {}
    cases_raw = payload.get("cases")
    if not isinstance(cases_raw, Sequence) or isinstance(cases_raw, str | bytes):
        return {}

    requests: dict[str, int] = {}
    for item in cases_raw:
        if not isinstance(item, Mapping):
            continue
        input_path_raw = item.get("input_path")
        if not isinstance(input_path_raw, str) or not input_path_raw.strip():
            continue
        input_path = _resolve_manifest_input_path(
            manifest_path=manifest_path,
            input_path=input_path_raw,
        )
        ticker, years = _extract_prewarm_request_from_input(
            input_path=input_path,
            default_years=default_years,
        )
        if ticker is None:
            continue
        current_years = requests.get(ticker, 0)
        requests[ticker] = max(current_years, years)
    return requests


def _resolve_manifest_input_path(*, manifest_path: Path, input_path: str) -> Path:
    path = Path(input_path)
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def _extract_prewarm_request_from_input(
    *,
    input_path: Path,
    default_years: int,
) -> tuple[str | None, int]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, default_years
    if not isinstance(payload, Mapping):
        return None, default_years
    ticker_raw = payload.get("ticker")
    if not isinstance(ticker_raw, str) or not ticker_raw.strip():
        return None, default_years
    ticker = ticker_raw.strip().upper()
    reports_raw = payload.get("reports")
    if isinstance(reports_raw, Sequence) and not isinstance(reports_raw, str | bytes):
        report_count = len(reports_raw)
        if report_count > 0:
            return ticker, report_count
    return ticker, default_years


def _resolve_prewarm_fetch_payload_fn() -> (
    Callable[[str, int], Mapping[str, object]] | None
):
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))
    try:
        from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.fetch.provider import (
            fetch_financial_payload,
        )
    except Exception:
        return None
    return fetch_financial_payload


def _optional_float(payload: Mapping[str, object], *, key: str) -> float | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise TypeError(f"{key} must be numeric")
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            return None
        try:
            return float(token)
        except ValueError as exc:
            raise TypeError(f"{key} must be numeric") from exc
    raise TypeError(f"{key} must be numeric")


def _default_cycle_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
