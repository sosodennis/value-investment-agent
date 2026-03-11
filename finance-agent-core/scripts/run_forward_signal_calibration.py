from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.forward_signals.domain.calibration.fitting_service import (  # noqa: E402
    fit_forward_signal_calibration_config,
)
from src.agents.fundamental.forward_signals.domain.calibration.io_service import (  # noqa: E402
    load_forward_signal_calibration_observations,
    write_forward_signal_calibration_artifact,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit forward-signal calibration mapping artifact from offline "
            "observation dataset (JSON array or JSONL)."
        ),
    )
    parser.add_argument(
        "--input", type=Path, required=True, help="Observation dataset path."
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output artifact path."
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=None,
        help="Optional fit report JSON output path.",
    )
    parser.add_argument(
        "--mapping-version",
        type=str,
        default=None,
        help="Artifact mapping_version. Defaults to timestamped version.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=120,
        help="Minimum usable samples required before fit; fallback otherwise.",
    )
    parser.add_argument(
        "--fit-source-multipliers",
        action="store_true",
        help="Fit source multipliers from data (else keep defaults).",
    )
    parser.add_argument(
        "--fit-metric-multipliers",
        action="store_true",
        help="Fit metric multipliers from data (else keep defaults).",
    )
    parser.add_argument(
        "--require-fit",
        action="store_true",
        help="Exit non-zero when fit falls back to default config.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping_version = args.mapping_version or _default_mapping_version()
    load_result = load_forward_signal_calibration_observations(args.input)
    fit_result = fit_forward_signal_calibration_config(
        load_result.observations,
        mapping_version=mapping_version,
        min_samples=max(int(args.min_samples), 1),
        fit_source_multipliers=bool(args.fit_source_multipliers),
        fit_metric_multipliers=bool(args.fit_metric_multipliers),
    )

    artifact = {
        "mapping_version": fit_result.config.mapping_version,
        "source_multiplier": fit_result.config.source_multiplier,
        "metric_multiplier": fit_result.config.metric_multiplier,
        "mapping_bins": [
            [upper, slope] for upper, slope in fit_result.config.mapping_bins
        ],
    }
    write_forward_signal_calibration_artifact(
        output_path=args.output,
        payload=artifact,
    )

    report_payload = {
        "input_path": str(args.input),
        "output_path": str(args.output),
        "mapping_version": fit_result.config.mapping_version,
        "fit": {
            "input_count": fit_result.report.input_count,
            "usable_count": fit_result.report.usable_count,
            "dropped_count": fit_result.report.dropped_count + load_result.dropped_rows,
            "load_dropped_count": load_result.dropped_rows,
            "min_samples_required": fit_result.report.min_samples_required,
            "used_fallback": fit_result.report.used_fallback,
            "fallback_reason": fit_result.report.fallback_reason,
            "mapping_bins_sample_count": fit_result.report.mapping_bins_sample_count,
        },
    }
    if args.report_output is not None:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(report_payload, ensure_ascii=False))
    if bool(args.require_fit) and fit_result.report.used_fallback:
        return 1
    return 0


def _default_mapping_version() -> str:
    now = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    return f"forward_signal_calibration_fit_{now}"


if __name__ == "__main__":
    raise SystemExit(main())
