from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.core_valuation.domain.parameterization.forward_signal_calibration_mapping_service import (  # noqa: E402
    FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV,
    clear_forward_signal_calibration_mapping_cache,
    load_forward_signal_calibration_mapping,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate forward signal calibration mapping artifact.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Optional mapping artifact path to validate.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.path is not None:
        os.environ[FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH_ENV] = str(args.path)
    clear_forward_signal_calibration_mapping_cache()
    result = load_forward_signal_calibration_mapping()

    print(
        json.dumps(
            {
                "mapping_version": result.config.mapping_version,
                "mapping_source": result.mapping_source,
                "mapping_path": result.mapping_path,
                "degraded_reason": result.degraded_reason,
            },
            ensure_ascii=False,
        )
    )
    if result.degraded_reason is not None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
