from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.domain.valuation.calibration import (  # noqa: E402
    build_forward_signal_calibration_observations,
    fit_forward_signal_calibration_config,
    serialize_observations,
    write_forward_signal_calibration_artifact,
)
from src.agents.fundamental.infrastructure.market_data.market_data_service import (  # noqa: E402
    market_data_service,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build forward-signal calibration observation dataset from replay "
            "report and optionally fit mapping artifact."
        ),
    )
    parser.add_argument(
        "--replay-report",
        type=Path,
        required=True,
        help="Replay report JSON path (expects results[] rows).",
    )
    parser.add_argument(
        "--dataset-output",
        type=Path,
        required=True,
        help="Output path for calibration observations JSONL.",
    )
    parser.add_argument(
        "--artifact-output",
        type=Path,
        default=None,
        help="Optional output path for fitted calibration artifact JSON.",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=None,
        help="Optional pipeline report JSON path.",
    )
    parser.add_argument(
        "--mapping-version",
        type=str,
        default=None,
        help="Mapping version when artifact fit enabled.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=120,
        help="Minimum samples required for fitted mapping.",
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=0.5,
        help="Correction gain from anchor pricing gap to target bp.",
    )
    parser.add_argument(
        "--adjustment-cap-bp",
        type=float,
        default=300.0,
        help="Absolute cap for target basis points.",
    )
    parser.add_argument(
        "--no-live-market-data",
        action="store_true",
        help="Disable live market snapshot fallback when replay row lacks anchor target.",
    )
    parser.add_argument(
        "--require-fit",
        action="store_true",
        help="Exit non-zero if artifact fit falls back due insufficient samples.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    replay_payload = _read_json(args.replay_report)
    results = replay_payload.get("results")
    if not isinstance(results, list):
        raise ValueError("replay report must contain results array")

    anchor_by_ticker, anchor_stats = _resolve_anchor_targets(
        results=results,
        allow_live_market_data=not args.no_live_market_data,
    )
    build_result = build_forward_signal_calibration_observations(
        replay_results=[item for item in results if isinstance(item, dict)],
        anchor_target_price_by_ticker=anchor_by_ticker,
        gain=float(args.gain),
        adjustment_cap_basis_points=float(args.adjustment_cap_bp),
    )
    serialized = serialize_observations(build_result.observations)
    _write_jsonl(args.dataset_output, serialized)

    fit_payload: dict[str, object] | None = None
    fit_used_fallback = False
    if args.artifact_output is not None:
        if args.mapping_version is None or not args.mapping_version.strip():
            raise ValueError(
                "--mapping-version is required when --artifact-output is set"
            )
        fit_result = fit_forward_signal_calibration_config(
            build_result.observations,
            mapping_version=args.mapping_version.strip(),
            min_samples=max(int(args.min_samples), 1),
        )
        artifact_payload = {
            "mapping_version": fit_result.config.mapping_version,
            "source_multiplier": fit_result.config.source_multiplier,
            "metric_multiplier": fit_result.config.metric_multiplier,
            "mapping_bins": [
                [upper, slope] for upper, slope in fit_result.config.mapping_bins
            ],
        }
        write_forward_signal_calibration_artifact(
            output_path=args.artifact_output,
            payload=artifact_payload,
        )
        fit_used_fallback = fit_result.report.used_fallback
        fit_payload = {
            "mapping_version": fit_result.config.mapping_version,
            "used_fallback": fit_result.report.used_fallback,
            "fallback_reason": fit_result.report.fallback_reason,
            "input_count": fit_result.report.input_count,
            "usable_count": fit_result.report.usable_count,
            "dropped_count": fit_result.report.dropped_count,
            "min_samples_required": fit_result.report.min_samples_required,
            "mapping_bins_sample_count": fit_result.report.mapping_bins_sample_count,
            "artifact_output": str(args.artifact_output),
        }

    pipeline_report = {
        "replay_report": str(args.replay_report),
        "dataset_output": str(args.dataset_output),
        "row_count": build_result.row_count,
        "usable_row_count": build_result.usable_row_count,
        "dropped_row_count": build_result.dropped_row_count,
        "observation_count": len(serialized),
        "dropped_reasons": build_result.dropped_reasons,
        "anchor_stats": anchor_stats,
        "fit": fit_payload,
    }
    if args.report_output is not None:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(
            json.dumps(pipeline_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(pipeline_report, ensure_ascii=False))

    if bool(args.require_fit) and fit_used_fallback:
        return 1
    return 0


def _resolve_anchor_targets(
    *,
    results: list[object],
    allow_live_market_data: bool,
) -> tuple[dict[str, float], dict[str, int]]:
    anchor_by_ticker: dict[str, float] = {}
    from_report = 0
    from_live = 0
    missing = 0

    for item in results:
        if not isinstance(item, dict):
            continue
        ticker = _coerce_non_empty_string(item.get("ticker"))
        if ticker is None:
            continue
        target = _coerce_float(item.get("target_consensus_mean_price"))
        if target is None:
            target = _coerce_float(item.get("target_mean_price"))
        if target is not None and target > 0.0:
            anchor_by_ticker[ticker] = target
            from_report += 1
            continue
        if not allow_live_market_data:
            missing += 1
            continue
        try:
            snapshot = market_data_service.get_market_snapshot(ticker)
        except Exception:  # noqa: BLE001
            missing += 1
            continue
        target = snapshot.target_mean_price
        if target is None or target <= 0.0:
            missing += 1
            continue
        anchor_by_ticker[ticker] = target
        from_live += 1

    return anchor_by_ticker, {
        "resolved_count": len(anchor_by_ticker),
        "from_report_count": from_report,
        "from_live_market_data_count": from_live,
        "missing_count": missing,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise TypeError("replay report root must be an object")
    return dict(parsed)


def _coerce_float(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        value = float(raw)
        if value != value:
            return None
        return value
    if isinstance(raw, str):
        normalized = raw.strip()
        if not normalized:
            return None
        try:
            value = float(normalized)
        except ValueError:
            return None
        if value != value:
            return None
        return value
    return None


def _coerce_non_empty_string(raw: object) -> str | None:
    if isinstance(raw, str) and raw:
        return raw
    return None


if __name__ == "__main__":
    raise SystemExit(main())
