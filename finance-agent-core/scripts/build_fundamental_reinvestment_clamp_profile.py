from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.domain.valuation.parameterization.reinvestment_clamp_profile_service import (  # noqa: E402
    REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION,
    ReinvestmentClampProfile,
    parse_reinvestment_clamp_profile,
)

INPUT_SCHEMA_VERSION = "fundamental_reinvestment_clamp_profile_input_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a versioned reinvestment clamp profile artifact from structured input.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input JSON path (fundamental_reinvestment_clamp_profile_input_v1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output profile JSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_payload = _read_payload(args.input)
    output_payload = _build_profile_payload(input_payload)
    profile = parse_reinvestment_clamp_profile(output_payload)
    _write_payload(path=args.output, profile=profile, payload=output_payload)
    print(
        json.dumps(
            {
                "input_path": str(args.input),
                "output_path": str(args.output),
                "schema_version": REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION,
                "profile_version": profile.profile_version,
                "gate_passed": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_payload(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("input root must be an object")
    return parsed


def _build_profile_payload(input_payload: Mapping[str, object]) -> dict[str, object]:
    schema_version = input_payload.get("schema_version")
    if schema_version != INPUT_SCHEMA_VERSION:
        raise ValueError("input_schema_version_mismatch")

    profile_version_raw = input_payload.get("profile_version")
    profile_version = (
        profile_version_raw.strip() if isinstance(profile_version_raw, str) else ""
    )
    if not profile_version:
        raise ValueError("profile_version_missing_or_invalid")

    dcf_growth_raw = input_payload.get("dcf_growth")
    if not isinstance(dcf_growth_raw, Mapping):
        raise ValueError("dcf_growth_missing_or_invalid")

    as_of_date_raw = input_payload.get("as_of_date")
    as_of_date = as_of_date_raw.strip() if isinstance(as_of_date_raw, str) else ""
    if not as_of_date:
        raise ValueError("as_of_date_missing_or_invalid")

    evidence_refs = _normalize_evidence_refs(input_payload.get("evidence_refs"))

    return {
        "schema_version": REINVESTMENT_CLAMP_PROFILE_SCHEMA_VERSION,
        "profile_version": profile_version,
        "as_of_date": as_of_date,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dcf_growth": {
            "severe_scope_mismatch_ratio_threshold": dcf_growth_raw.get(
                "severe_scope_mismatch_ratio_threshold"
            ),
            "severe_mismatch_capex_terminal_lower_min": dcf_growth_raw.get(
                "severe_mismatch_capex_terminal_lower_min"
            ),
            "severe_mismatch_capex_terminal_lower_year1_ratio": dcf_growth_raw.get(
                "severe_mismatch_capex_terminal_lower_year1_ratio"
            ),
            "severe_mismatch_wc_terminal_lower_min": dcf_growth_raw.get(
                "severe_mismatch_wc_terminal_lower_min"
            ),
            "severe_mismatch_wc_terminal_lower_year1_ratio": dcf_growth_raw.get(
                "severe_mismatch_wc_terminal_lower_year1_ratio"
            ),
        },
        "evidence_refs": evidence_refs,
    }


def _normalize_evidence_refs(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("evidence_refs_invalid")
    normalized: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("evidence_refs_invalid")
        token = item.strip()
        if not token:
            continue
        normalized.append(token)
    return normalized


def _write_payload(
    *,
    path: Path,
    profile: ReinvestmentClampProfile,
    payload: Mapping[str, object],
) -> None:
    serialized = {
        **payload,
        "schema_version": profile.schema_version,
        "profile_version": profile.profile_version,
        "dcf_growth": {
            "severe_scope_mismatch_ratio_threshold": profile.dcf_growth.severe_scope_mismatch_ratio_threshold,
            "severe_mismatch_capex_terminal_lower_min": profile.dcf_growth.severe_mismatch_capex_terminal_lower_min,
            "severe_mismatch_capex_terminal_lower_year1_ratio": profile.dcf_growth.severe_mismatch_capex_terminal_lower_year1_ratio,
            "severe_mismatch_wc_terminal_lower_min": profile.dcf_growth.severe_mismatch_wc_terminal_lower_min,
            "severe_mismatch_wc_terminal_lower_year1_ratio": profile.dcf_growth.severe_mismatch_wc_terminal_lower_year1_ratio,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(serialized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
