from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.domain.valuation.parameterization.reinvestment_clamp_profile_service import (  # noqa: E402
    parse_reinvestment_clamp_profile,
)

DEFAULT_MAX_AGE_DAYS_ENV = "FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MAX_AGE_DAYS"
DEFAULT_MIN_EVIDENCE_REFS_ENV = (
    "FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MIN_EVIDENCE_REFS"
)
_DEFAULT_MAX_AGE_DAYS = 21
_DEFAULT_MIN_EVIDENCE_REFS = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate fundamental reinvestment clamp profile artifact.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to reinvestment clamp profile JSON artifact.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=_resolve_default_max_age_days(),
        help="Maximum allowed age of as_of_date in days.",
    )
    parser.add_argument(
        "--min-evidence-refs",
        type=int,
        default=_resolve_default_min_evidence_refs(),
        help="Minimum required number of evidence refs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output validation JSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.path)
    profile = parse_reinvestment_clamp_profile(payload)
    issues, as_of_date, age_days, evidence_ref_count = _validate_payload(
        payload=payload,
        max_age_days=args.max_age_days,
        min_evidence_refs=args.min_evidence_refs,
    )

    output = {
        "path": str(args.path),
        "schema_version": profile.schema_version,
        "profile_version": profile.profile_version,
        "as_of_date": as_of_date,
        "age_days": age_days,
        "evidence_ref_count": evidence_ref_count,
        "max_age_days": args.max_age_days,
        "min_evidence_refs": args.min_evidence_refs,
        "gate_passed": len(issues) == 0,
        "issues": issues,
    }
    serialized = json.dumps(output, ensure_ascii=False)
    print(serialized)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")

    if issues:
        return 1
    return 0


def _read_payload(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("profile root must be an object")
    return parsed


def _validate_payload(
    *,
    payload: Mapping[str, object],
    max_age_days: int,
    min_evidence_refs: int,
) -> tuple[list[str], str | None, int | None, int]:
    issues: list[str] = []

    as_of_raw = payload.get("as_of_date")
    as_of_date_value = as_of_raw.strip() if isinstance(as_of_raw, str) else ""
    as_of_date = as_of_date_value if as_of_date_value else None

    parsed_as_of_date = _parse_as_of_date(as_of_date_value)
    age_days: int | None = None
    if parsed_as_of_date is None:
        issues.append("as_of_date_missing_or_invalid")
    else:
        age_days = _compute_age_days(parsed_as_of_date)
        if age_days < 0:
            issues.append("as_of_date_in_future")
        if age_days > max_age_days:
            issues.append(
                f"profile_stale:age_days={age_days}>max_age_days={max_age_days}"
            )

    evidence_refs_raw = payload.get("evidence_refs")
    evidence_ref_count = _count_evidence_refs(evidence_refs_raw)
    if evidence_ref_count < min_evidence_refs:
        issues.append(
            "evidence_refs_insufficient:"
            f"count={evidence_ref_count}<min_evidence_refs={min_evidence_refs}"
        )

    return issues, as_of_date, age_days, evidence_ref_count


def _parse_as_of_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _compute_age_days(as_of_date: date) -> int:
    today = datetime.now(timezone.utc).date()
    return (today - as_of_date).days


def _count_evidence_refs(raw: object) -> int:
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return 0
    count = 0
    for item in raw:
        if not isinstance(item, str):
            continue
        if item.strip():
            count += 1
    return count


def _resolve_default_max_age_days() -> int:
    raw = os.getenv(DEFAULT_MAX_AGE_DAYS_ENV)
    parsed = _coerce_positive_int(raw)
    return parsed if parsed is not None else _DEFAULT_MAX_AGE_DAYS


def _resolve_default_min_evidence_refs() -> int:
    raw = os.getenv(DEFAULT_MIN_EVIDENCE_REFS_ENV)
    parsed = _coerce_non_negative_int(raw)
    return parsed if parsed is not None else _DEFAULT_MIN_EVIDENCE_REFS


def _coerce_positive_int(raw: object) -> int | None:
    value = _coerce_int(raw)
    if value is None:
        return None
    return value if value > 0 else None


def _coerce_non_negative_int(raw: object) -> int | None:
    value = _coerce_int(raw)
    if value is None:
        return None
    return value if value >= 0 else None


def _coerce_int(raw: object) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            return None
        try:
            return int(float(token))
        except ValueError:
            return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
