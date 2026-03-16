from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agents.technical.subdomains.governance import (
    build_technical_governance_registry,
    build_technical_governance_report,
    registry_from_payload,
    registry_to_payload,
    report_to_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate technical governance registry and drift report."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write governance report JSON.",
    )
    parser.add_argument(
        "--baseline",
        required=False,
        help="Optional baseline registry/report JSON to compare.",
    )
    parser.add_argument(
        "--registry-output",
        required=False,
        help="Optional path to write registry JSON.",
    )
    args = parser.parse_args()

    registry = build_technical_governance_registry()
    baseline_registry = None
    issues: list[str] = []

    if args.baseline:
        baseline_path = Path(args.baseline)
        try:
            payload = json.loads(baseline_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "registry" in payload:
                payload = payload["registry"]
            if isinstance(payload, dict):
                baseline_registry = registry_from_payload(payload)
            else:
                issues.append("baseline_registry_invalid_payload")
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            issues.append(f"baseline_registry_load_failed:{exc}")

    report = build_technical_governance_report(
        registry=registry,
        baseline_registry=baseline_registry,
        extra_issues=issues,
    )

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(report_to_payload(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if args.registry_output:
        registry_path = Path(args.registry_output)
        registry_path.write_text(
            json.dumps(registry_to_payload(registry), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
