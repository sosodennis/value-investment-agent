from __future__ import annotations

import re
from datetime import date, datetime


def _normalize_text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized else None


def _normalize_accession_number(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    accession_match = re.search(r"(\d{10}-\d{2}-\d{6})", stripped)
    if accession_match is not None:
        return accession_match.group(1)
    digits = re.sub(r"\D", "", stripped)
    if len(digits) != 18:
        return None
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def _normalize_cik(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        return str(value)
    if isinstance(value, str):
        digits = re.sub(r"\D", "", value)
        if not digits:
            return None
        return digits
    return None
